from datetime import date
from decimal import Decimal

from arzan_quant.panel import reconstruct_daily_state
from arzan_quant.schema import Observation


def make_observation(observation_id: str, observed_at: str, price: str) -> Observation:
    return Observation.from_dict(
        {
            "observation_id": observation_id,
            "observed_at": observed_at,
            "retailer_id": "alpha",
            "store_id": "alpha_astana",
            "city_id": "astana",
            "retailer_product_id": "alpha:milk",
            "canonical_product_id": "milk",
            "price": price,
            "regular_price": None,
            "currency": "KZT",
            "is_available": True,
            "is_promotion": False,
        }
    )


def test_daily_state_uses_last_event_of_day_and_carries_forward() -> None:
    events = [
        make_observation("1", "2026-08-01T06:00:00+00:00", "500"),
        make_observation("2", "2026-08-01T18:00:00+00:00", "520"),
        make_observation("3", "2026-08-03T07:00:00+00:00", "550"),
    ]
    panel = reconstruct_daily_state(events, date(2026, 8, 1), date(2026, 8, 4))
    assert [row["price"] for row in panel] == [
        Decimal(520),
        Decimal(520),
        Decimal(550),
    ]
