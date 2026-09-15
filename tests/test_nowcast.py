import pytest

pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")
from arzan_quant.nowcast import evaluate_nowcast


def vintage_data():
    months = pd.date_range("2020-01-01", periods=36, freq="MS")
    signal = np.sin(np.arange(36))
    features = pd.DataFrame(
        {
            "month": months,
            "available_at": months + pd.offsets.MonthBegin(1),
            "index_change": signal,
            "diffusion_signal": np.cos(np.arange(36)),
        }
    )
    targets = pd.DataFrame(
        {
            "month": months,
            "released_at": months + pd.offsets.MonthBegin(1) + pd.Timedelta(days=10),
            "value": 0.5 + signal * 0.4,
        }
    )
    return features, targets


def test_release_aware_nowcast_and_future_revision_invariance():
    x, y = vintage_data()
    result = evaluate_nowcast(x, y)
    assert result["status"] == "evaluated"
    assert result["metrics"]["index_only"]["mae"] < result["metrics"]["historical_mean"]["mae"]
    revision = y.copy()
    revision["released_at"] = pd.Timestamp("2030-01-01")
    revision["value"] = 999
    changed = evaluate_nowcast(x, pd.concat([y, revision]))
    assert changed == result
    late = x.copy()
    late["available_at"] = pd.Timestamp("2030-01-01")
    late["index_change"] = 999
    assert evaluate_nowcast(pd.concat([x, late]), y) == result


def test_nowcast_insufficient_history():
    x, y = vintage_data()
    assert evaluate_nowcast(x.iloc[:6], y.iloc[:6])["status"] == "insufficient_released_history"
