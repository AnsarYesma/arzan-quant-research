"""Validated, versioned configuration for full research runs."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class ResearchSettings:
    start: str
    end: str
    max_state_age_days: int = 7
    min_match_confidence: float = 0.9
    assume_store_success_confirms_state: bool = False
    retrospective_mapping: bool = False
    assume_continuous_observation: bool = False
    feed_groups: dict[str, str] = field(default_factory=dict)
    min_train_days: int = 60
    test_days: int = 30
    min_train_events: int = 30
    exposure_days: int = 3
    seed: int = 20260913
    grocery_categories: list[str] = field(default_factory=list)
    min_index_weight_coverage: float = 0.8

    def __post_init__(self):
        if date.fromisoformat(self.start) >= date.fromisoformat(self.end):
            raise ValueError("start must precede the exclusive end date")
        for name in (
            "max_state_age_days",
            "min_train_days",
            "test_days",
            "min_train_events",
            "exposure_days",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not 0 <= self.min_match_confidence <= 1:
            raise ValueError("min_match_confidence must be in [0, 1]")
        if not 0 < self.min_index_weight_coverage <= 1:
            raise ValueError("min_index_weight_coverage must be in (0, 1]")
        if not isinstance(self.grocery_categories, list) or any(
            not isinstance(value, str) or not value for value in self.grocery_categories
        ):
            raise ValueError("grocery_categories must be a list of category IDs")
        for name in (
            "assume_store_success_confirms_state",
            "retrospective_mapping",
            "assume_continuous_observation",
        ):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be boolean")
        if not isinstance(self.feed_groups, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) or not k or not v
            for k, v in self.feed_groups.items()
        ):
            raise ValueError("feed_groups must map retailer IDs to non-empty family names")

    @classmethod
    def read(cls, path: Path) -> ResearchSettings:
        return cls(**json.loads(path.read_text()))

    def as_dict(self) -> dict:
        return asdict(self)
