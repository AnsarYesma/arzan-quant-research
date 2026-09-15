"""End-to-end research orchestration with persisted provenance and explicit gates."""

from __future__ import annotations

import json
from importlib.metadata import version
from pathlib import Path

from .analytics import descriptive_network, price_index, promotion_diagnostics
from .evaluation import feature_frame, walk_forward
from .experiments import focused_binned_excitation, response_timing, timestamp_audit
from .features import build_features
from .manifest import sha256_file, verify_manifest
from .nowcast import evaluate_nowcast
from .reporting import create_figure, create_report, dump_json
from .settings import ResearchSettings
from .warehouse import construct_panel, load_exports, rows


def run_research(
    exports: list[Path],
    output: Path,
    cfg: ResearchSettings,
    opening: Path | None = None,
    weights: Path | None = None,
    monthly_features: Path | None = None,
    targets: Path | None = None,
    robustness: bool = True,
    resume_panel: bool = False,
) -> dict:
    import duckdb
    import pandas as pd

    if (monthly_features is None) != (targets is None):
        raise ValueError("Provide both monthly feature vintages and target vintages for nowcasting")
    if not resume_panel:
        output.mkdir(parents=True, exist_ok=False)
    output.chmod(0o700)
    provenance = {
        "status": "running",
        "settings": cfg.as_dict(),
        "code_sha256": {p.name: sha256_file(p) for p in sorted(Path(__file__).parent.glob("*.py"))},
        "dependencies": {
            name: version(name) for name in ("duckdb", "pyarrow", "numpy", "scipy", "pandas")
        },
    }
    for name, path in [
        ("opening", opening),
        ("weights", weights),
        ("monthly_features", monthly_features),
        ("targets", targets),
    ]:
        if path is not None:
            provenance[name + "_sha256"] = sha256_file(path)
    previous = None
    if resume_panel:
        previous = json.loads((output / "run.json").read_text())
        if previous.get("status") != "failed" or previous.get("settings") != cfg.as_dict():
            raise ValueError("Panel resume requires a failed run with identical settings")
        for name in ("warehouse.py", "schema.py", "settings.py", "manifest.py"):
            if previous["code_sha256"][name] != provenance["code_sha256"][name]:
                raise ValueError("Panel construction code changed; start a fresh run")
        for name in ("opening", "weights", "monthly_features", "targets"):
            if previous.get(name + "_sha256") != provenance.get(name + "_sha256"):
                raise ValueError("Optional input changed; start a fresh run")
        sources = [s for s in previous.get("inputs", {}).get("sources", []) if "export_id" in s]
        if len(sources) != len(exports):
            raise ValueError("Export list changed; start a fresh run")
        for root, source in zip(exports, sources):
            if sha256_file(root / "manifest.json") != source["manifest_sha256"]:
                raise ValueError("Export manifest changed; start a fresh run")
            verify_manifest(root / "manifest.json")
        with duckdb.connect(str(output / "research.duckdb"), read_only=True) as check:
            tables = {r[0] for r in check.execute("SHOW TABLES").fetchall()}
            if (
                not {"observations", "transitions", "coverage", "panel"} <= tables
                or "basket" in tables
            ):
                raise ValueError("Resume requires a completed panel before analytics")
        backup = output / f"attempt-{len(list(output.glob('attempt-*.json'))) + 1}.json"
        dump_json(backup, previous)
        provenance["resumed_panel"] = {
            "previous_attempt": backup.name,
            "previous_attempt_sha256": sha256_file(backup),
            "checkpoint_sha256": sha256_file(output / "research.duckdb"),
        }
        provenance["inputs"] = previous["inputs"]
    dump_json(output / "run.json", provenance)
    con = duckdb.connect(str(output / "research.duckdb"))
    con.execute("SET threads=4")
    con.execute("SET memory_limit='2GB'")
    try:
        if previous is None:
            inputs = load_exports(con, exports, opening)
            provenance["inputs"] = inputs
            panel = construct_panel(con, cfg)
        else:
            inputs = previous["inputs"]
            con.execute("SET TimeZone='UTC'")
            panel = rows(
                con,
                """SELECT count(*) AS panel_rows,
                count(*) FILTER(WHERE state_eligible) AS eligible_states,
                count(*) FILTER(WHERE outcome_eligible) AS eligible_transitions,
                count(*) FILTER(WHERE outcome_eligible AND abs(log_return)>1e-10) AS daily_changes,
                count(*) FILTER(WHERE match_eligible) AS matched_states,
                count(*) FILTER(WHERE known_collection_problem) AS collection_problem_rows,
                count(*) FILTER(WHERE evidence_type='unknown') AS unknown_rows
                FROM transitions""",
            )[0]
        print(f"Panel ready: {panel['panel_rows']:,} states", flush=True)
        feature_summary = build_features(con, cfg)
        print(f"Features ready: {feature_summary['rows']:,} targets", flush=True)
        frame = feature_frame(con)
        evaluation, _ = walk_forward(
            frame, cfg, prediction_path=output / "predictions.parquet", retain_predictions=False
        )
        del frame
        model_fits = evaluation.pop("models")
        dump_json(output / "model_fits.json", model_fits)
        timing = response_timing(con)
        excitation = focused_binned_excitation(con, cfg)
        timing_audit = timestamp_audit(con)
        network = descriptive_network(con)
        promotions = promotion_diagnostics(con)
        index = price_index(con, cfg, weights)
        index_rows = rows(
            con, "SELECT date, index_value, weight_coverage FROM price_index ORDER BY date"
        )
        variants = {}
        if robustness:
            for name, args in [
                ("source_barcode", {"matching": "barcode"}),
                ("no_promotions", {"exclude_promotions": True}),
                ("recent_state_only", {"max_age_days": 1}),
            ]:
                print(f"Evaluating robustness: {name}", flush=True)
                description = build_features(con, cfg, **args)
                variant_frame = feature_frame(con)
                assessment, _ = walk_forward(variant_frame, cfg, retain_predictions=False)
                del variant_frame
                assessment.pop("models")
                variants[name] = {"features": description, "evaluation": assessment}
            # The persisted primary feature tables must match the primary evaluation.
            build_features(con, cfg)
        nowcast = {"status": "awaiting_monthly_feature_and_target_vintages"}
        if targets is not None:
            nowcast = evaluate_nowcast(pd.read_parquet(monthly_features), pd.read_parquet(targets))
        result = {
            "status": "complete",
            "assume_continuous_observation": cfg.assume_continuous_observation,
            "data_kind": (
                "synthetic validation"
                if opening is None
                and all(
                    s.get("status") == "synthetic" for s in inputs["sources"] if "export_id" in s
                )
                else "private research data"
            ),
            "inputs": inputs,
            "panel": panel,
            "features": feature_summary,
            "evaluation": evaluation,
            "response_timing": timing,
            "excitation_experiment": excitation,
            "timestamp_audit": timing_audit,
            "network": network,
            "promotions": promotions,
            "index": index,
            "nowcast": nowcast,
            "robustness": variants,
        }
        dump_json(output / "results.json", result)
        create_figure(output, result, index_rows)
        create_report(output, result, index_rows)
        con.execute("CHECKPOINT")
        provenance["status"] = "complete"
        provenance["artifacts"] = {
            str(p.relative_to(output)): sha256_file(p)
            for p in output.rglob("*")
            if p.is_file()
            and ".tmp" not in p.parts
            and p.name not in ("run.json", "research.duckdb.wal")
        }
        dump_json(output / "run.json", provenance)
        return result
    except (Exception, KeyboardInterrupt) as error:
        provenance.update(
            {"status": "failed", "error_type": type(error).__name__, "error": str(error)}
        )
        dump_json(output / "run.json", provenance)
        raise
    finally:
        con.close()
