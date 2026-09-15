from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

from .schema import Observation


def reconstruct_daily_state(
    observations: Iterable[Observation], start: date, end: date
) -> list[dict[str, object]]:
    """Reference implementation for tests and small pilots.

    State is carried forward only after the first observed event. This function does
    not impute across known failed crawl dates; production reconstruction will join
    crawl coverage before deciding which rows are analytically observable.
    """
    if end <= start:
        raise ValueError("end must be after start")

    grouped: dict[tuple[str, str], list[Observation]] = {}
    for observation in observations:
        key = (observation.store_id, observation.retailer_product_id)
        grouped.setdefault(key, []).append(observation)

    result: list[dict[str, object]] = []
    for key, events in sorted(grouped.items()):
        events.sort(key=lambda event: (event.observed_at, event.observation_id))
        position = 0
        state: Observation | None = None
        day = start
        while day < end:
            next_day = day + timedelta(days=1)
            while position < len(events) and events[position].observed_at.date() < next_day:
                if events[position].observed_at.date() >= start:
                    state = events[position]
                position += 1
            if state is not None:
                result.append(
                    {
                        "date": day,
                        "store_id": key[0],
                        "retailer_product_id": key[1],
                        "canonical_product_id": state.canonical_product_id,
                        "price": state.price,
                        "is_available": state.is_available,
                        "last_observed_at": state.observed_at,
                    }
                )
            day = next_day
    return result
