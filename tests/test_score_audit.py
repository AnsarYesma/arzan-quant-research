import importlib.util
import json
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")
duckdb = pytest.importorskip("duckdb")


def test_paired_audit_identical_forecasts_and_directional_nulls(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "score_audit", Path(__file__).parents[1] / "tools/audit_continuous_predictions.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    run = tmp_path / "run"
    prediction_path = run / "predictions.parquet"
    prediction_path.mkdir(parents=True)
    for name in ("hazard_baseline", "hazard_diffusion"):
        pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=10),
                "model": name,
                "probability": 0.1,
                "changed": [0, 1] * 5,
            }
        ).to_parquet(prediction_path / f"{name}.parquet", index=False)
    db = duckdb.connect(str(run / "research.duckdb"))
    db.execute("""CREATE TABLE features AS SELECT * FROM
        (VALUES (0,0,0.0,0.0), (1,1,0.1,0.1), (1,1,0.1,-0.1))
        v(peer_active_days,changed,peer_mark,magnitude)""")
    db.close()
    output = tmp_path / "audit"
    module.audit(run, output)
    result = json.loads((output / "paired_score_audit.json").read_text())
    assert result["observations"] == 10
    assert result["diffusion_minus_baseline_brier"] == 0
    assert result["block_bootstrap_95_percent_interval"] == [0, 0]
    association = result["descriptive_peer_association"]
    assert association[0]["same_direction_fraction"] is None
    assert association[1]["same_direction_fraction"] == 0.5
    assert association[1]["independent_direction_agreement"] == 0.5

    scores_only = tmp_path / "scores-only"
    module.audit(run, scores_only, include_association=False)
    only = json.loads((scores_only / "paired_score_audit.json").read_text())
    assert only["descriptive_peer_association"] == []
    for key in (
        "observations",
        "diffusion_minus_baseline_brier",
        "block_bootstrap_95_percent_interval",
    ):
        assert only[key] == result[key]
