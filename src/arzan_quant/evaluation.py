"""Expanding-window evaluation with day-level boundaries and training-only fitting."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .models import (
    BASE_NUMERIC,
    CATEGORICAL,
    DIFFUSION_NUMERIC,
    Encoder,
    calibration,
    fit_boosted_tree,
    fit_glm,
    fit_marks,
    metrics,
    predict_glm,
)
from .settings import ResearchSettings

MODEL_COLUMNS = (
    ["row_id", "date", "changed", "magnitude"] + BASE_NUMERIC + DIFFUSION_NUMERIC + CATEGORICAL
)

EVALUATION_PROTOCOL = {
    "primary_metric": "brier",
    "secondary_metrics": ["log_loss", "calibration"],
    "validation": "expanding chronological test blocks",
    "comparison_rule": "with/without competitor features within each model family",
    "tuning": "fixed before evaluation; no test-window selection",
}


def feature_frame(con, where="", parameters=None):
    """Load only model inputs, with compact dictionary-backed identifiers."""
    columns = ", ".join(MODEL_COLUMNS)
    table = con.execute(
        f"SELECT {columns} FROM features {where} ORDER BY date, row_id", parameters or []
    ).to_arrow_table()
    return table.to_pandas(categories=CATEGORICAL)


def walk_forward(frame, cfg: ResearchSettings, *, prediction_path=None, retain_predictions=True):
    frame = frame.copy(deep=False)
    frame["date"] = pd.to_datetime(frame["date"])
    if prediction_path is not None:
        prediction_path = Path(prediction_path)
        prediction_path.mkdir(parents=True, exist_ok=False)
    folds, predictions, models = [], [], []
    boundary = date.fromisoformat(cfg.start) + timedelta(days=cfg.min_train_days)
    end = date.fromisoformat(cfg.end)
    while boundary < end:
        test_end = min(end, boundary + timedelta(days=cfg.test_days))
        train = frame[frame.date < pd.Timestamp(boundary)]
        test = frame[(frame.date >= pd.Timestamp(boundary)) & (frame.date < pd.Timestamp(test_end))]
        fold = {
            "train_end_exclusive": str(boundary),
            "test_end_exclusive": str(test_end),
            "train_rows": len(train),
            "test_rows": len(test),
            "train_events": int(train.changed.sum()),
        }
        if (
            train.changed.sum() < cfg.min_train_events
            or not len(test)
            or train.changed.nunique() < 2
        ):
            fold.update({"status": "insufficient_data", "metrics": {}})
            folds.append(fold)
            boundary = test_end
            continue
        y, actual = test.changed.to_numpy(float), test.magnitude.to_numpy(float)
        rate = (train.changed.sum() + 0.5) / (len(train) + 1)
        values = {
            "persistence": (np.zeros(len(test)), np.zeros(len(test))),
            "training_rate": (np.full(len(test), rate), np.zeros(len(test))),
        }
        fold_models = {}
        mark_predictions = {}
        for name, diffusion, family in [
            ("hazard_baseline", False, "logistic"),
            ("hazard_diffusion", True, "logistic"),
            ("marked_intensity", True, "poisson"),
        ]:
            encoder = Encoder.fit(train, diffusion)
            print(
                f"Fitting {name}: test {boundary} to {test_end}, {len(train):,} training rows",
                flush=True,
            )
            x_train, x_test = (
                encoder.transform(train, sparse_output=True),
                encoder.transform(test, sparse_output=True),
            )
            beta, diagnostic = fit_glm(x_train, train.changed.to_numpy(float), family)
            p = predict_glm(x_test, beta, family)
            selected = train.changed.to_numpy() == 1
            mark_beta = fit_marks(x_train[selected], train.magnitude.to_numpy(float)[selected])
            expected = p * (x_test @ mark_beta)
            del x_train, x_test
            values[name] = p, expected
            mark_predictions[diffusion] = expected
            fold_models[name] = {
                "encoder": encoder.as_dict(),
                "coefficients": beta.tolist(),
                "mark_coefficients": mark_beta.tolist(),
                "diagnostics": diagnostic,
            }
        for name, diffusion in [
            ("boosted_baseline", False),
            ("boosted_competitor", True),
        ]:
            print(
                f"Fitting {name}: test {boundary} to {test_end}, {len(train):,} training rows",
                flush=True,
            )
            p, fitted = fit_boosted_tree(
                train,
                test,
                diffusion=diffusion,
                seed=cfg.seed + boundary.toordinal(),
            )
            values[name] = p, mark_predictions[diffusion]
            fold_models[name] = fitted
        fold.update({"status": "evaluated", "metrics": {}, "calibration": {}})
        for name, (p, expected) in values.items():
            fold["metrics"][name] = metrics(y, p, actual, expected)
            fold["calibration"][name] = calibration(y, p)
            prediction = pd.DataFrame(
                {
                    "row_id": test.row_id.to_numpy(),
                    "date": test.date.to_numpy(),
                    "model": name,
                    "probability": p,
                    "expected_return": expected,
                    "changed": y,
                    "actual_return": actual,
                    "train_end_exclusive": str(boundary),
                }
            )
            if prediction_path is not None:
                prediction.to_parquet(prediction_path / f"{boundary}-{name}.parquet", index=False)
            if retain_predictions:
                predictions.append(prediction)
            del prediction
        models.append({"train_end_exclusive": str(boundary), "models": fold_models})
        folds.append(fold)
        boundary = test_end
    predictions = pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame()
    aggregate = {}
    for fold in folds:
        for name, scores in fold["metrics"].items():
            total = aggregate.setdefault(name, {key: 0 for key in scores})
            for key, value in scores.items():
                total[key] += (
                    value
                    if key in ("n", "events")
                    else scores["n"] * (value**2 if key == "return_rmse" else value)
                )
    for scores in aggregate.values():
        for key in scores:
            if key not in ("n", "events"):
                scores[key] /= scores["n"]
                if key == "return_rmse":
                    scores[key] = float(np.sqrt(scores[key]))
    return {
        "status": "evaluated" if aggregate else "insufficient_history_or_eligible_events",
        "protocol": EVALUATION_PROTOCOL,
        "folds": folds,
        "aggregate": aggregate,
        "models": models,
    }, predictions
