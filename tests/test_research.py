import json

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("pyarrow")
pytest.importorskip("pandas")
pytest.importorskip("scipy")
pytest.importorskip("matplotlib")

from test_features import prepare
from test_nowcast import vintage_data

from arzan_quant.analytics import descriptive_network
from arzan_quant.fixtures import generate_export
from arzan_quant.nowcast import build_monthly_vintage
from arzan_quant.research import run_research
from arzan_quant.settings import ResearchSettings


def test_complete_synthetic_run_and_nowcast_branch(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    root = generate_export(tmp_path / "input", days=240)
    x, y = vintage_data()
    x.to_parquet(tmp_path / "monthly.parquet", index=False)
    y.to_parquet(tmp_path / "targets.parquet", index=False)
    output = tmp_path / "run"
    result = run_research(
        [root],
        output,
        ResearchSettings.read(root / "settings.json"),
        monthly_features=tmp_path / "monthly.parquet",
        targets=tmp_path / "targets.parquet",
    )
    assert result["evaluation"]["status"] == "evaluated"
    assert result["nowcast"]["status"] == "evaluated"
    assert all(v["evaluation"]["status"] == "evaluated" for v in result["robustness"].values())
    edges = {(e["source_retailer"], e["target_retailer"]): e for e in result["network"]}
    assert edges[("alpha", "beta")]["rate_difference"] > 0.1
    assert abs(edges[("alpha", "gamma")]["rate_difference"]) < 0.05
    scores = result["evaluation"]["aggregate"]
    assert scores["hazard_diffusion"]["brier"] < scores["hazard_baseline"]["brier"]
    assert (output / "diagnostics.png").stat().st_size > 10000
    assert '<svg id="network"' in (output / "dashboard.html").read_text()
    report = (output / "report.md").read_text()
    assert "Monthly model" in report and "source_barcode" in report
    provenance = json.loads((output / "run.json").read_text())
    assert provenance["status"] == "complete"
    assert "research.duckdb" in provenance["artifacts"]
    assert not any(".tmp" in name for name in provenance["artifacts"])
    monthly = build_monthly_vintage(output, tmp_path / "vintage.parquet", "2025-08-29T00:00:00Z")
    assert len(monthly) == 1
    assert str(monthly.iloc[0].month.date()) == "2025-07-01"
    with pytest.raises(ValueError, match="snapshot"):
        build_monthly_vintage(output, tmp_path / "bad-vintage.parquet", "2025-02-01T00:00:00Z")
    with pytest.raises(FileExistsError):
        run_research([root], output, ResearchSettings.read(root / "settings.json"))


def test_independent_control_has_no_large_directional_excess(tmp_path):
    root = generate_export(tmp_path / "null", days=240, independent=True)
    con = prepare(root, ResearchSettings.read(root / "settings.json"))
    edges = descriptive_network(con)
    assert edges
    assert max(abs(e["rate_difference"]) for e in edges) < 0.05
    con.close()


def test_resume_completed_panel_matches_fresh_run_and_rejects_changed_inputs(tmp_path, monkeypatch):
    import json

    from arzan_quant import research
    from arzan_quant.fixtures import generate_export
    from arzan_quant.settings import ResearchSettings

    root = generate_export(tmp_path / "resume-source", days=80)
    cfg = ResearchSettings.read(root / "settings.json")
    output = tmp_path / "resume-run"
    original = research.build_features

    def fail_after_panel(*args, **kwargs):
        raise RuntimeError("Simulated feature interruption")

    monkeypatch.setattr(research, "build_features", fail_after_panel)
    with pytest.raises(RuntimeError, match="Simulated"):
        research.run_research([root], output, cfg, robustness=False)
    assert json.loads((output / "run.json").read_text())["status"] == "failed"
    with pytest.raises(ValueError, match="identical settings"):
        research.run_research(
            [root],
            output,
            ResearchSettings(**(cfg.as_dict() | {"test_days": 15})),
            robustness=False,
            resume_panel=True,
        )
    monkeypatch.setattr(research, "build_features", original)
    resumed = research.run_research([root], output, cfg, robustness=False, resume_panel=True)
    fresh = research.run_research([root], tmp_path / "fresh-run", cfg, robustness=False)
    import pandas as pd

    pd.testing.assert_frame_equal(
        pd.DataFrame(resumed.pop("network"))
        .sort_values(["source_retailer", "target_retailer"])
        .reset_index(drop=True),
        pd.DataFrame(fresh.pop("network"))
        .sort_values(["source_retailer", "target_retailer"])
        .reset_index(drop=True),
        check_exact=False,
        rtol=1e-12,
        atol=1e-12,
    )

    def assert_equivalent(actual, expected):
        if isinstance(expected, dict):
            assert actual.keys() == expected.keys()
            for key in expected:
                assert_equivalent(actual[key], expected[key])
        elif isinstance(expected, list):
            assert len(actual) == len(expected)
            for left, right in zip(actual, expected):
                assert_equivalent(left, right)
        elif isinstance(expected, float):
            assert actual == pytest.approx(expected, rel=1e-10, abs=1e-12)
        else:
            assert actual == expected

    assert_equivalent(resumed, fresh)
    assert json.loads((output / "attempt-1.json").read_text())["status"] == "failed"
    assert json.loads((output / "run.json").read_text())["status"] == "complete"
    with pytest.raises(ValueError, match="failed run"):
        research.run_research([root], output, cfg, robustness=False, resume_panel=True)
