from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any


class ContractError(ValueError):
    """Raised when an input record violates the agreed research contract."""


REQUIRED_FIELDS = frozenset(
    {
        "observation_id",
        "observed_at",
        "retailer_id",
        "store_id",
        "city_id",
        "retailer_product_id",
        "price",
        "currency",
        "is_available",
        "is_promotion",
    }
)


def _required_string(record: dict[str, Any], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} must be a non-empty string")
    return value.strip()


def parse_timestamp(value: Any, field: str = "observed_at") -> datetime:
    if not isinstance(value, str):
        raise ContractError(f"{field} must be an ISO 8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ContractError(f"{field} is not valid ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractError(f"{field} must include an explicit UTC offset")
    return parsed.astimezone(UTC)


def parse_decimal(value: Any, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ContractError(f"{field} must be decimal-compatible") from exc
    if not parsed.is_finite():
        raise ContractError(f"{field} must be finite")
    return parsed


@dataclass(frozen=True)
class Observation:
    observation_id: str
    observed_at: datetime
    retailer_id: str
    store_id: str
    city_id: str
    retailer_product_id: str
    canonical_product_id: str | None
    price: Decimal
    regular_price: Decimal | None
    currency: str
    is_available: bool
    is_promotion: bool
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, record: dict[str, Any]) -> Observation:
        missing = REQUIRED_FIELDS.difference(record)
        if missing:
            raise ContractError(f"missing required fields: {', '.join(sorted(missing))}")

        price = parse_decimal(record["price"], "price")
        if price <= 0:
            raise ContractError("price must be positive")

        regular_price = None
        if record.get("regular_price") is not None:
            regular_price = parse_decimal(record["regular_price"], "regular_price")
            if regular_price <= 0:
                raise ContractError("regular_price must be positive when present")

        for field in ("is_available", "is_promotion"):
            if type(record[field]) is not bool:
                raise ContractError(f"{field} must be boolean")

        canonical = record.get("canonical_product_id")
        if canonical is not None and (not isinstance(canonical, str) or not canonical.strip()):
            raise ContractError("canonical_product_id must be null or a non-empty string")

        return cls(
            observation_id=_required_string(record, "observation_id"),
            observed_at=parse_timestamp(record["observed_at"]),
            retailer_id=_required_string(record, "retailer_id"),
            store_id=_required_string(record, "store_id"),
            city_id=_required_string(record, "city_id"),
            retailer_product_id=_required_string(record, "retailer_product_id"),
            canonical_product_id=canonical.strip() if canonical else None,
            price=price,
            regular_price=regular_price,
            currency=_required_string(record, "currency"),
            is_available=record["is_available"],
            is_promotion=record["is_promotion"],
            raw=dict(record),
        )
