"""Write aggregate coverage diagnostics without exposing offer-level records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

from arzan_quant.manifest import sha256_file, verify_manifest
from arzan_quant.warehouse import rows


def audit_export(root: Path, output: Path):
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    checked = verify_manifest(manifest_path)
    # The supplementary checksum list also covers the schema and publication policy.
    checksum_count = 0
    for line in (root / "SHA256SUMS").read_text().splitlines():
        digest, relative = line.split(maxsplit=1)
        path = (root / relative.lstrip("*")).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Checksum path escapes export")
        if sha256_file(path) != digest:
            raise ValueError(f"Checksum mismatch: {relative}")
        checksum_count += 1
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'; SET threads=4; SET memory_limit='1GB'")
    # Use manifest paths so both partitioned and flat observation exports work.
    paths = [
        str(root / f["path"])
        for f in manifest["files"]
        if f["path"].startswith("price_observations/")
    ]
    con.read_parquet(paths, hive_partitioning=False, union_by_name=True).create_view("observations")
    queries = {
        "scope": """SELECT count(*) AS observations, min(observed_at) AS first_observation_utc,
            max(observed_at) AS last_observation_utc, count(DISTINCT retailer_id) AS retailers,
            count(DISTINCT city_id) AS cities, count(DISTINCT category_id) AS category_ids,
            count(*) FILTER(WHERE link_valid_from IS NOT NULL) AS historically_dated_link_rows,
            count(*) FILTER(WHERE canonical_product_id IS NULL) AS unlinked_rows,
            count(*) FILTER(WHERE price<=0 OR NOT isfinite(price::DOUBLE)) AS invalid_price_rows
            FROM observations""",
        "months": """SELECT strftime(observed_at,'%Y-%m') AS month,
            count(*) AS observations, count(DISTINCT retailer_id) AS retailers,
            count(DISTINCT city_id) AS cities FROM observations GROUP BY 1 ORDER BY 1""",
        "retailers": """SELECT retailer_id, any_value(retailer_name) AS retailer_name,
            count(*) AS observations, min(observed_at) AS first_observation,
            max(observed_at) AS last_observation FROM observations GROUP BY 1 ORDER BY observations DESC""",
        "categories": """SELECT category_id, category_path, count(*) AS observations
            FROM observations GROUP BY ALL ORDER BY observations DESC""",
    }
    result = {name: rows(con, query) for name, query in queries.items()}
    result.update(
        {
            "manifest_sha256": sha256_file(manifest_path),
            "audit_script_sha256": sha256_file(Path(__file__)),
            "verified_parquet_files": len(checked),
            "verified_checksum_entries": checksum_count,
            "manifest_status": manifest.get("status"),
            "manifest_totals": manifest["totals"],
            "cutoff_exclusive": manifest["cutoff_exclusive"],
            "mapping_snapshot_at": manifest["mapping_snapshot_at"],
        }
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, default=str, allow_nan=False) + "\n")
    con.close()
    print(json.dumps(result["scope"], default=str))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit_export(args.export, args.output)
