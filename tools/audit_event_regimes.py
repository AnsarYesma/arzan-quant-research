"""Audit whether retained events repeat a source offer's preceding market state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

from arzan_quant.manifest import sha256_file
from arzan_quant.warehouse import rows


def audit(export: Path, output: Path):
    manifest = json.loads((export / "manifest.json").read_text())
    paths = [
        str(export / f["path"])
        for f in manifest["files"]
        if f["path"].startswith("price_observations/")
    ]
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'; SET threads=2; SET memory_limit='1GB'")
    con.read_parquet(paths, hive_partitioning=False, union_by_name=True).create_view("observations")
    summary = rows(
        con,
        """WITH ordered AS (
        SELECT retailer_id, observed_at, price, regular_price, is_available, currency,
          lag(observed_at) OVER w AS previous_at, lag(price) OVER w AS previous_price,
          lag(regular_price) OVER w AS previous_regular, lag(is_available) OVER w AS previous_available,
          lag(currency) OVER w AS previous_currency,
          count(*) OVER (PARTITION BY retailer_id,store_id,retailer_product_id,observed_at) AS multiplicity
        FROM observations
        WINDOW w AS (PARTITION BY retailer_id,store_id,retailer_product_id
          ORDER BY observed_at,try_cast(observation_id AS HUGEINT),observation_id)
        ) SELECT strftime(observed_at,'%Y-%m') AS month,retailer_id,count(*) AS rows,
          count(*) FILTER(WHERE previous_at IS NOT NULL) AS with_predecessor,
          count(*) FILTER(WHERE previous_at IS NOT NULL AND price=previous_price
            AND regular_price IS NOT DISTINCT FROM previous_regular
            AND is_available IS NOT DISTINCT FROM previous_available
            AND currency IS NOT DISTINCT FROM previous_currency) AS repeated_market_state_rows,
          count(*) FILTER(WHERE previous_at IS NOT NULL AND price<>previous_price) AS changed_price_rows,
          count(*) FILTER(WHERE previous_at IS NOT NULL AND is_available IS DISTINCT FROM previous_available) AS availability_change_rows,
          count(*) FILTER(WHERE previous_at IS NOT NULL AND regular_price IS DISTINCT FROM previous_regular) AS reference_price_change_rows,
          count(*) FILTER(WHERE previous_at IS NOT NULL AND price=previous_price
            AND regular_price IS NOT DISTINCT FROM previous_regular
            AND currency IS NOT DISTINCT FROM previous_currency
            AND is_available IS DISTINCT FROM previous_available) AS availability_only_rows,
          count(*) FILTER(WHERE multiplicity>1) AS tied_timestamp_rows
        FROM ordered GROUP BY ALL ORDER BY month,retailer_id""",
    )
    result = {
        "manifest_sha256": sha256_file(export / "manifest.json"),
        "script_sha256": sha256_file(Path(__file__)),
        "monthly_retailer_summary": summary,
        "definition": "Repeated market state compares each retained row with the previous row for the same retailer/store/source product, using numeric observation ID to break timestamp ties. First rows have no comparison; tied timestamps are reported separately. No records are deleted by this diagnostic.",
    }
    output.write_text(json.dumps(result, indent=2) + "\n")
    con.close()
    print(output)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--export", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    audit(a.export, a.output)
