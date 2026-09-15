"""Convert API NDJSON landing files to the same verified export interface as backfills."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from .manifest import sha256_file
from .schema import Observation, parse_timestamp
from .warehouse import OPTIONAL_COLUMNS


def package_landing(source: Path, output: Path, start: str, end: str, snapshot: str):
    import pyarrow as pa
    import pyarrow.parquet as pq

    first, cutoff, at = (parse_timestamp(value) for value in (start, end, snapshot))
    if first >= cutoff or at < cutoff:
        raise ValueError("Window must be ordered and snapshot cannot precede cutoff")
    schema = pa.schema(
        [
            ("observation_id", pa.string()),
            ("observed_at", pa.timestamp("us", tz="UTC")),
            *[
                (name, pa.string())
                for name in (
                    "retailer_id",
                    "store_id",
                    "city_id",
                    "retailer_product_id",
                    "currency",
                )
            ],
            ("price", pa.float64()),
            ("is_available", pa.bool_()),
            ("is_promotion", pa.bool_()),
            *[
                (
                    name,
                    {
                        "VARCHAR": pa.string(),
                        "DOUBLE": pa.float64(),
                        "INTEGER": pa.int32(),
                        "VARCHAR[]": pa.list_(pa.string()),
                        "TIMESTAMPTZ": pa.timestamp("us", tz="UTC"),
                    }[kind],
                )
                for name, kind in OPTIONAL_COLUMNS.items()
            ],
        ]
    )
    output.mkdir(parents=True, exist_ok=False)
    output.chmod(0o700)
    path = output / "price_observations" / "events.parquet"
    path.parent.mkdir()
    opener = gzip.open if source.suffix == ".gz" else open
    count = 0
    batch = []
    with (
        opener(source, "rt", encoding="utf-8") as stream,
        pq.ParquetWriter(path, schema, compression="zstd") as writer,
    ):
        for line in stream:
            raw = json.loads(line)
            obs = Observation.from_dict(raw)
            if not first <= obs.observed_at < cutoff:
                raise ValueError("Landing observation falls outside requested window")
            record = {name: raw.get(name) for name in schema.names}
            record["observed_at"] = obs.observed_at
            record["price"] = float(obs.price)
            for name, kind in OPTIONAL_COLUMNS.items():
                value = record[name]
                if value is None:
                    continue
                if kind == "TIMESTAMPTZ":
                    record[name] = parse_timestamp(value, name)
                elif kind == "DOUBLE":
                    record[name] = float(value)
                elif kind == "INTEGER":
                    record[name] = int(value)
            batch.append(record)
            count += 1
            if len(batch) >= 50000:
                writer.write_table(pa.Table.from_pylist(batch, schema=schema))
                batch = []
        if batch:
            writer.write_table(pa.Table.from_pylist(batch, schema=schema))
    manifest = {
        "format_version": 1,
        "schema_version": "1.0",
        "export_id": "api-" + sha256_file(source)[:16],
        "status": "incremental",
        "cutoff_exclusive": cutoff.isoformat(),
        "observed_from_inclusive": first.isoformat(),
        "mapping_snapshot_at": at.isoformat(),
        "source_sha256": sha256_file(source),
        "totals": {"price_observations": count, "daily_crawl_coverage_rows": 0},
        "files": [
            {
                "path": "price_observations/events.parquet",
                "row_count": count,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        ],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
