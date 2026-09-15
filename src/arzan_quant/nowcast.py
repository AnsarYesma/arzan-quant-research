"""Monthly target-vintage evaluation. No target revision is visible before release."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .schema import parse_timestamp


def evaluate_nowcast(monthly_features, vintages, min_train_months=12):
    """Feature rows: month, available_at, index_change, diffusion_signal.

    Target rows: month, released_at, value. At an origin, use the newest released
    training vintage and score against the target's first release. Features for each
    historical month are frozen to its month-end origin, not revised retrospectively.
    """
    required_x = {"month", "available_at", "index_change", "diffusion_signal"}
    required_y = {"month", "released_at", "value"}
    if required_x - set(monthly_features) or required_y - set(vintages):
        raise ValueError("Nowcast feature or target-vintage columns are missing")
    if type(min_train_months) is not int or min_train_months < 1:
        raise ValueError("Minimum training history must be a positive integer")
    x, y = monthly_features.copy(), vintages.copy()
    for data in (x, y):
        data["month"] = pd.to_datetime(data.month).dt.to_period("M").dt.to_timestamp()
    x["available_at"] = pd.to_datetime(x.available_at, utc=True)
    y["released_at"] = pd.to_datetime(y.released_at, utc=True)
    if y[["month", "released_at"]].duplicated().any():
        raise ValueError("Target month/release timestamps must be unique")
    if not np.isfinite(y.value.astype(float)).all():
        raise ValueError("Targets must be finite")
    # Freeze one feature vintage per historical month, visible by the next month's start.
    x["origin"] = (
        pd.to_datetime(x.forecast_at, utc=True)
        if "forecast_at" in x
        else (x.month + pd.offsets.MonthBegin(1)).dt.tz_localize("UTC")
    )
    if (
        x[["month", "available_at", "origin"]].isna().any().any()
        or y[["month", "released_at"]].isna().any().any()
    ):
        raise ValueError("Month and availability timestamps must not be missing")
    if x[["month", "available_at", "origin"]].duplicated().any():
        raise ValueError("Feature month/availability/origin keys must be unique")
    x = (
        x[x.available_at <= x.origin]
        .sort_values(["origin", "available_at"], ascending=[True, False])
        .drop_duplicates("month", keep="first")
    )
    if not np.isfinite(x[["index_change", "diffusion_signal"]].astype(float)).all().all():
        raise ValueError("Nowcast features must be finite")
    predictions = []
    for row in x.sort_values("month").itertuples():
        known = y[(y.released_at <= row.origin) & (y.month < row.month)]
        known = known.sort_values("released_at").drop_duplicates("month", keep="last")
        train = x[(x.month < row.month) & (x.available_at <= row.origin)].merge(
            known[["month", "value"]], on="month"
        )
        target = y[y.month == row.month].sort_values("released_at")
        if len(train) < min_train_months or target.empty:
            continue
        # This is a nowcast only while the target has not already been released.
        if target.iloc[0].released_at <= row.origin:
            continue
        actual = float(target.iloc[0].value)
        for name, columns in [
            ("historical_mean", []),
            ("index_only", ["index_change"]),
            ("index_and_diffusion", ["index_change", "diffusion_signal"]),
        ]:
            if not columns:
                pred = float(train.value.mean())
            else:
                values = train[columns].to_numpy(float)
                means, scales = values.mean(0), values.std(0)
                scales = np.where(scales > 1e-8, scales, 1)
                design = np.column_stack([np.ones(len(train)), (values - means) / scales])
                reg = np.eye(design.shape[1])
                reg[0, 0] = 0
                beta = np.linalg.solve(
                    design.T @ design + reg, design.T @ train.value.to_numpy(float)
                )
                now = np.array([getattr(row, c) for c in columns])
                pred = float(np.r_[1, (now - means) / scales] @ beta)
            predictions.append(
                {
                    "month": str(row.month.date()),
                    "origin": row.origin.isoformat(),
                    "model": name,
                    "prediction": pred,
                    "actual_first_release": actual,
                    "train_months": len(train),
                }
            )
    summary = {}
    for name in {p["model"] for p in predictions}:
        error = np.array(
            [p["prediction"] - p["actual_first_release"] for p in predictions if p["model"] == name]
        )
        summary[name] = {
            "n": len(error),
            "mae": float(abs(error).mean()),
            "rmse": float(np.sqrt((error**2).mean())),
        }
    return {
        "status": "evaluated" if predictions else "insufficient_released_history",
        "minimum_training_months": min_train_months,
        "metrics": summary,
        "predictions": predictions,
    }


def build_monthly_vintage(run: Path, output: Path, forecast_at: str):
    """Emit only the latest complete month's signal with honest availability timestamps."""
    import duckdb

    provenance = json.loads((run / "run.json").read_text())
    if provenance["status"] != "complete":
        raise ValueError("Monthly vintages require a completed research run")
    available = max(
        parse_timestamp(s["snapshot_at"])
        for s in provenance["inputs"]["sources"]
        if "snapshot_at" in s
    )
    forecast = parse_timestamp(forecast_at)
    if forecast < available:
        raise ValueError("Forecast time cannot precede input snapshot availability")
    with duckdb.connect(str(run / "research.duckdb"), read_only=True) as con:
        monthly = con.execute("""WITH index_months AS (
          SELECT date_trunc('month',date)::DATE AS month, avg(index_value) AS mean_index,
            count(index_value) AS valid_days, max(date)=last_day(max(date)) AS month_complete,
            day(last_day(max(date))) AS expected_days
          FROM price_index GROUP BY 1
        ), changes AS (
          SELECT *, lag(mean_index) OVER(ORDER BY month) AS previous_index,
            lag(month) OVER(ORDER BY month) AS previous_month,
            lag(month_complete AND valid_days>=.8*expected_days) OVER(ORDER BY month) AS previous_complete
          FROM index_months
        ), signals AS (
          SELECT date_trunc('month',date)::DATE AS month, avg(peer_decay) AS diffusion_signal
          FROM features GROUP BY 1
        ) SELECT c.month, 100*(mean_index/previous_index-1) AS index_change, s.diffusion_signal
          FROM changes c JOIN signals s USING(month)
          WHERE month_complete AND valid_days>=.8*expected_days AND previous_complete
            AND previous_month=month-INTERVAL 1 MONTH
          ORDER BY month DESC LIMIT 1""").df()
    if monthly.empty:
        raise ValueError(
            "Need two consecutive complete index months and eligible diffusion features"
        )
    month = monthly.iloc[0].month
    if pd.Timestamp(forecast) < (pd.Timestamp(month) + pd.offsets.MonthBegin(1)).tz_localize("UTC"):
        raise ValueError("Forecast time precedes the end of the signal month")
    monthly["available_at"] = pd.Timestamp(available)
    monthly["forecast_at"] = pd.Timestamp(forecast)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Open exclusively so an earlier forecast vintage cannot be overwritten accidentally.
    with output.open("xb") as stream:
        monthly.to_parquet(stream, index=False)
    return monthly
