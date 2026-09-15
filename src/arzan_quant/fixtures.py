"""Synthetic exports with known lagged propagation and collection failures."""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .manifest import sha256_file


def write_export(
    root: Path, records: list[dict], coverage: list[dict], export_id: str, cutoff: datetime
) -> Path:
    import pyarrow as pa
    import pyarrow.parquet as pq

    root.mkdir(parents=True, exist_ok=False)
    files = []
    for relative, values in [
        ("price_observations/events.parquet", records),
        ("crawl_coverage/daily_crawl_coverage.parquet", coverage),
    ]:
        if not values:
            continue
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(values), path, compression="zstd")
        files.append(
            {
                "path": relative,
                "row_count": len(values),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    manifest = {
        "format_version": 1,
        "schema_version": "1.0",
        "export_id": export_id,
        "status": "synthetic",
        "cutoff_exclusive": cutoff.isoformat(),
        "mapping_snapshot_at": cutoff.isoformat(),
        "totals": {"price_observations": len(records), "daily_crawl_coverage_rows": len(coverage)},
        "files": files,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return root


def generate_export(
    root: Path, days: int = 240, seed: int = 20260913, independent: bool = False
) -> Path:
    """Alpha shocks raise beta's next-day hazard; gamma is an independent control.

    Direction and magnitude follow alpha with noise. City and category labels are
    synthetic; no production rows or metadata are used. A failed crawl emits no event
    and a returning crawl records the then-current state. Promotion episodes last 3d.
    """
    if days < 10:
        raise ValueError("Synthetic export needs at least ten days")
    rng = random.Random(seed)
    start = datetime(2025, 1, 1, tzinfo=UTC)
    retailers = ["alpha", "beta", "gamma"]
    cities = ["city_one", "city_two"]
    records, coverage = [], []
    prices, emitted, promo_until = {}, {}, {}
    changes = {}
    event_id = 0
    for day in range(-1, days):
        when = start + timedelta(days=day, hours=12)
        for city in cities:
            for retailer in retailers:
                failed = (
                    day >= 0 and retailer == "beta" and city == "city_one" and day % 67 in (30, 31)
                )
                if day >= 0:
                    coverage.append(
                        {
                            "retailer_id": retailer,
                            "store_id": f"{retailer}_{city}",
                            "date": when.date(),
                            "crawl_status": "failed" if failed else "successful",
                            "is_complete_utc_day": True,
                        }
                    )
                for product in range(12):
                    key = retailer, city, product
                    if key not in prices:
                        prices[key] = 400 + product * 50
                        promo_until[key] = -2
                    source = changes.get((day - 1, "alpha", city, product), 0)
                    follows = retailer == "beta" and source != 0 and not independent
                    shock = 0.0
                    if day >= 0 and rng.random() < (0.72 if follows else 0.045):
                        shock = source if follows else rng.choice([-0.03, 0.03, 0.06])
                        prices[key] = round(prices[key] * (1 + shock), 2)
                    changes[(day, retailer, city, product)] = shock
                    if day >= 0 and rng.random() < 0.006:
                        promo_until[key] = day + 3
                    promo = day < promo_until[key]
                    actual = round(prices[key] * (0.9 if promo else 1), 2)
                    state = (actual, prices[key] if promo else None, promo)
                    if failed or emitted.get(key) == state:
                        continue
                    emitted[key] = state
                    event_id += 1
                    records.append(
                        {
                            "observation_id": str(event_id),
                            "observed_at": when,
                            "retailer_id": retailer,
                            "store_id": f"{retailer}_{city}",
                            "city_id": city,
                            "retailer_product_id": f"{retailer}_{product}",
                            "canonical_product_id": f"product_{product}",
                            "category_id": f"category_{product // 4}",
                            "brand": f"brand_{product % 3}",
                            "price": actual,
                            "regular_price": state[1],
                            "currency": "KZT",
                            "is_available": True,
                            "is_promotion": promo,
                            "quantity": 1000.0,
                            "unit": "g",
                            "pack_count": 1,
                            "unit_price": actual,
                            "barcodes": [f"synthetic_{product}"],
                            "match_method": "manual",
                            "match_confidence": 1.0,
                            "match_status": "approved",
                            "link_record_created_at": start - timedelta(days=10),
                            "link_valid_from": start - timedelta(days=10),
                            "link_valid_to": None,
                        }
                    )
    cutoff = start + timedelta(days=days)
    write_export(root, records, coverage, f"synthetic-{seed}-{days}-{independent}", cutoff)
    truth = {
        "seed": seed,
        "days": days,
        "independent": independent,
        "effect": "alpha -> beta, next day, same city and product" if not independent else "none",
        "baseline_change_probability": 0.045,
        "follower_probability_given_source_change": 0.72,
        "note": "Probabilities refer to latent non-promotion changes, not censored retained rows.",
    }
    (root / "truth.json").write_text(json.dumps(truth, indent=2) + "\n")
    settings = {
        "start": start.date().isoformat(),
        "end": cutoff.date().isoformat(),
        "assume_store_success_confirms_state": True,
        "max_state_age_days": 365,
        "min_train_days": 60,
        "test_days": 30,
        "min_train_events": 30,
    }
    settings["grocery_categories"] = [f"category_{i}" for i in range(3)]
    (root / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    return root


def generate_monthly_history(output: Path, months: int = 48, seed: int = 20260913):
    """Separate synthetic monthly experiment for testing target-vintage evaluation."""
    import numpy as np
    import pandas as pd

    if months < 15:
        raise ValueError("Monthly demonstration needs at least fifteen months")
    output.mkdir(parents=True, exist_ok=False)
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=months, freq="MS")
    index = rng.normal(0, 0.7, months)
    diffusion = rng.normal(0, 0.3, months)
    features = pd.DataFrame(
        {
            "month": dates,
            "available_at": dates + pd.offsets.MonthBegin(1),
            "index_change": index,
            "diffusion_signal": diffusion,
        }
    )
    targets = pd.DataFrame(
        {
            "month": dates,
            "released_at": dates + pd.offsets.MonthBegin(1) + pd.Timedelta(days=10),
            "value": 0.5 + 0.4 * index + 0.8 * diffusion + rng.normal(0, 0.04, months),
        }
    )
    revisions = targets.copy()
    revisions["released_at"] = revisions.released_at + pd.Timedelta(days=45)
    revisions["value"] = revisions.value + rng.normal(0, 0.03, months)
    features.to_parquet(output / "monthly_features.parquet", index=False)
    pd.concat([targets, revisions]).to_parquet(output / "target_vintages.parquet", index=False)
    (output / "truth.json").write_text(
        json.dumps(
            {
                "kind": "independent synthetic monthly validation",
                "seed": seed,
                "months": months,
                "index_coefficient": 0.4,
                "diffusion_coefficient": 0.8,
                "first_release_delay_days": 10,
                "revision_delay_days": 45,
            },
            indent=2,
        )
        + "\n"
    )
