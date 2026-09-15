"""Refit the same chronological models on declared grocery targets from a completed run.

Peer/context exposures retain the primary retail universe. This isolates target
composition without pretending the frozen category assignments are historical vintages.
"""

from __future__ import annotations

import argparse
import json
from importlib.metadata import version
from pathlib import Path

import duckdb

from arzan_quant.evaluation import feature_frame, walk_forward
from arzan_quant.manifest import sha256_file
from arzan_quant.reporting import dump_json
from arzan_quant.settings import ResearchSettings


def evaluate(run: Path, scope_path: Path, output: Path):
    provenance = json.loads((run / "run.json").read_text())
    if provenance["status"] != "complete":
        raise ValueError("Primary run must be complete")
    scope = json.loads(scope_path.read_text())
    categories = scope["category_ids"]
    if not categories or len(categories) != len(set(categories)):
        raise ValueError("Provide a nonempty unique list of grocery category IDs")
    con = duckdb.connect(str(run / "research.duckdb"), read_only=True)
    frame = feature_frame(
        con,
        "WHERE category_id IN (SELECT unnest(?))",
        [categories],
    )
    con.close()
    output.mkdir(parents=True, exist_ok=False)
    output.chmod(0o700)
    evidence = {
        "status": "running",
        "parent_run_sha256": sha256_file(run / "run.json"),
        "scope_sha256": sha256_file(scope_path),
        "script_sha256": sha256_file(Path(__file__)),
        "settings": provenance["settings"],
        "dependencies": {name: version(name) for name in provenance["dependencies"]},
        "code_sha256": {
            p.name: sha256_file(p) for p in sorted(Path("src/arzan_quant").glob("*.py"))
        },
        "target_rows": len(frame),
        "label": scope["label"],
        "exposure_universe": "Unchanged broad-retail primary exposures; target rows restricted to declared grocery categories",
    }
    dump_json(output / "run.json", evidence)
    try:
        assessment, _ = walk_forward(
            frame,
            ResearchSettings(**provenance["settings"]),
            prediction_path=output / "predictions.parquet",
            retain_predictions=False,
        )
        dump_json(output / "model_fits.json", assessment.pop("models"))
        dump_json(output / "results.json", assessment)
        evidence["status"] = "complete"
        evidence["artifacts"] = {
            str(p.relative_to(output)): sha256_file(p)
            for p in output.rglob("*")
            if p.is_file() and p.name != "run.json"
        }
        dump_json(output / "run.json", evidence)
        print(json.dumps(assessment["aggregate"], indent=2))
    except Exception as exc:
        evidence.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        dump_json(output / "run.json", evidence)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.run, args.scope, args.output)
