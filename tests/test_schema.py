from datetime import UTC
from decimal import Decimal

import pytest

from arzan_quant.schema import ContractError, Observation


def valid_record() -> dict[str, object]:
    return {
        "observation_id": "1",
        "observed_at": "2026-08-01T06:00:00+00:00",
        "retailer_id": "alpha",
        "store_id": "alpha_astana",
        "city_id": "astana",
        "retailer_product_id": "alpha:milk",
        "canonical_product_id": None,
        "price": "500.00",
        "regular_price": None,
        "currency": "KZT",
        "is_available": True,
        "is_promotion": False,
    }


def test_parses_contract_record() -> None:
    observation = Observation.from_dict(valid_record())
    assert observation.price == Decimal("500.00")
    assert observation.observed_at.tzinfo == UTC
    assert observation.canonical_product_id is None


def test_rejects_naive_timestamp() -> None:
    record = valid_record()
    record["observed_at"] = "2026-08-01T06:00:00"
    with pytest.raises(ContractError, match="explicit UTC offset"):
        Observation.from_dict(record)


def test_rejects_nonpositive_price() -> None:
    record = valid_record()
    record["price"] = "0"
    with pytest.raises(ContractError, match="positive"):
        Observation.from_dict(record)
