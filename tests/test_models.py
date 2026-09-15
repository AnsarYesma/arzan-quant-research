import pytest

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")
pytest.importorskip("scipy")

from arzan_quant.evaluation import walk_forward
from arzan_quant.models import Encoder, fit_glm, fit_marks, predict_glm
from arzan_quant.settings import ResearchSettings


def test_hazard_recovers_known_effect_and_mark_slope():
    rng = np.random.default_rng(42)
    x = np.column_stack([np.ones(8000), rng.normal(size=8000)])
    p = 1 / (1 + np.exp(-(-2 + 1.5 * x[:, 1])))
    y = rng.binomial(1, p)
    beta, diagnostic = fit_glm(x, y)
    assert diagnostic["converged"]
    assert abs(beta[1] - 1.5) < 0.15
    assert abs(beta[0] + 2) < 0.15
    marks = 0.01 + 0.04 * x[:, 1] + rng.normal(0, 0.001, len(x))
    assert abs(fit_marks(x, marks)[1] - 0.04) < 0.001
    for family in ("logistic", "poisson"):
        beta, _ = fit_glm(x, y, family)
        predictions = predict_glm(x, beta, family)
        assert np.isfinite(predictions).all()
        assert ((predictions >= 0) & (predictions <= 1)).all()


def frame():
    rng = np.random.default_rng(3)
    dates = pd.date_range("2025-01-01", periods=120)
    data = pd.DataFrame(
        {
            "date": dates,
            "row_id": np.arange(120),
            "changed": rng.binomial(1, 0.3, 120),
            "magnitude": rng.normal(0, 0.02, 120),
            "retailer_id": "r",
            "city_id": "c",
            "category_id": "cat",
            "day_of_week": dates.dayofweek,
            "lag_promotion": False,
            "lag_return": 0.0,
            "lag_state_age": 1.0,
            "days_since_own_change": 10.0,
            "own_change_rate_7d": 0.1,
            "own_change_rate_30d": 0.1,
            "own_change_rate_90d": 0.1,
            "peer_active_days": rng.binomial(1, 0.2, 120),
            "peer_mark": 0.0,
            "peer_decay": 0.0,
            "cross_city_count": 0.0,
            "category_count": 0.0,
            "cross_category_count": 0.0,
            "peer_active_1d": 0.0,
            "peer_active_3d": 0.0,
            "peer_active_7d": 0.0,
            "peer_active_14d": 0.0,
            "cheapest_peer_log_gap": 0.0,
            "mean_peer_log_gap": 0.0,
            "was_cheapest": 0.0,
            "priced_peer_families": 0.0,
        }
    )
    data.loc[data.changed == 0, "magnitude"] = 0
    return data


def test_training_encoder_and_first_fold_ignore_future():
    data = frame()
    cfg = ResearchSettings(
        "2025-01-01", "2025-05-01", min_train_days=60, test_days=30, min_train_events=5
    )
    first, _ = walk_forward(data, cfg)
    altered = data.copy()
    altered.loc[altered.date >= "2025-04-01", "peer_active_days"] = 99999
    altered.loc[altered.date >= "2025-04-01", "changed"] = 1
    second, _ = walk_forward(altered, cfg)
    assert first["models"][0] == second["models"][0]
    assert first["folds"][0] == second["folds"][0]
    encoder = Encoder.fit(data.iloc[:60])
    assert len(encoder.transform(data.iloc[60:])) == 60


def test_insufficient_history_gates_models():
    result, predictions = walk_forward(
        frame().iloc[:10], ResearchSettings("2025-01-01", "2025-02-01")
    )
    assert result["status"] == "insufficient_history_or_eligible_events"
    assert predictions.empty


def test_sparse_design_and_fits_match_dense_with_unseen_categories():
    from scipy import sparse

    data = frame()
    data["retailer_id"] = ["r" + str(i % 7) for i in range(len(data))]
    encoder = Encoder.fit(data.iloc[:90])
    held = data.iloc[90:].copy()
    held.loc[held.index[0], "retailer_id"] = "unseen"
    for sample in (data, held):
        dense = encoder.transform(sample)
        compact = encoder.transform(sample, sparse_output=True)
        assert sparse.issparse(compact)
        np.testing.assert_array_equal(compact.toarray(), dense)
    x = encoder.transform(data)
    compact = encoder.transform(data, sparse_output=True)
    y = data.changed.to_numpy(float)
    for family in ("logistic", "poisson"):
        dense_beta, _ = fit_glm(x, y, family)
        sparse_beta, _ = fit_glm(compact, y, family)
        np.testing.assert_allclose(
            predict_glm(x, dense_beta, family),
            predict_glm(compact, sparse_beta, family),
            atol=1e-6,
            rtol=1e-5,
        )
    np.testing.assert_allclose(
        fit_marks(x, data.magnitude.to_numpy(float)),
        fit_marks(compact, data.magnitude.to_numpy(float)),
        atol=1e-10,
    )


def test_streamed_predictions_match_in_memory(tmp_path):
    data = frame()
    cfg = ResearchSettings(
        "2025-01-01", "2025-05-01", min_train_days=60, test_days=30, min_train_events=5
    )
    expected, predictions = walk_forward(data, cfg)
    for name in ("retailer_id", "city_id", "category_id", "day_of_week"):
        data[name] = data[name].astype("category")
    actual, empty = walk_forward(
        data, cfg, prediction_path=tmp_path / "predictions.parquet", retain_predictions=False
    )
    assert empty.empty
    for model, scores in expected["aggregate"].items():
        assert actual["aggregate"][model] == pytest.approx(scores)
    restored = pd.read_parquet(tmp_path / "predictions.parquet")
    order = ["train_end_exclusive", "model", "row_id"]
    pd.testing.assert_frame_equal(
        restored.sort_values(order).reset_index(drop=True),
        predictions.sort_values(order).reset_index(drop=True),
    )
