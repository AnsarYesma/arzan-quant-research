from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path


def generate_observations(seed: int = 20260913, days: int = 45) -> list[dict[str, object]]:
    """Create deterministic synthetic diffusion events with no production data."""
    rng = random.Random(seed)
    start = datetime(2026, 8, 1, 6, tzinfo=UTC)
    retailers = ("retailer_alpha", "retailer_beta", "retailer_gamma")
    products = ("milk_1l", "rice_1kg", "eggs_10")
    base_prices = {"milk_1l": 500, "rice_1kg": 700, "eggs_10": 800}
    current = {(r, p): float(base_prices[p]) for r in retailers for p in products}
    records: list[dict[str, object]] = []
    observation_id = 1

    for offset in range(days):
        day = start + timedelta(days=offset)
        for product in products:
            if rng.random() < 0.18:
                shock = rng.choice((-1, 1)) * rng.choice((0.03, 0.05, 0.08))
                for lag, retailer in enumerate(retailers):
                    if lag and rng.random() < 0.2:
                        continue
                    key = (retailer, product)
                    current[key] = round(current[key] * (1 + shock + rng.uniform(-0.005, 0.005)), 2)
                    promo = shock < 0 and rng.random() < 0.7
                    records.append(
                        {
                            "observation_id": str(observation_id),
                            "observed_at": (day + timedelta(hours=3 * lag)).isoformat(),
                            "retailer_id": retailer,
                            "retailer_name": retailer.replace("_", " ").title(),
                            "store_id": f"{retailer}_astana",
                            "store_name": f"{retailer} Astana",
                            "city_id": "astana",
                            "city": "Astana",
                            "retailer_product_id": f"{retailer}:{product}",
                            "canonical_product_id": product,
                            "product_name": product.replace("_", " ").title(),
                            "category_id": "synthetic_grocery",
                            "category_path": ["Synthetic", "Grocery"],
                            "price": f"{current[key]:.2f}",
                            "regular_price": (
                                f"{current[key] / (1 + shock):.2f}" if promo else None
                            ),
                            "currency": "KZT",
                            "is_available": True,
                            "is_promotion": promo,
                            "quantity": "1.0",
                            "unit": "piece",
                            "unit_price": f"{current[key]:.2f}",
                            "match_method": "synthetic_exact",
                            "match_confidence": 1.0,
                            "match_status": "synthetic",
                        }
                    )
                    observation_id += 1
    return records


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            stream.write("\n")
