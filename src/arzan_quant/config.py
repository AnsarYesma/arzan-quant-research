from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ApiConfig:
    base_url: str
    api_key: str

    @classmethod
    def from_environment(cls) -> ApiConfig:
        base_url = os.environ.get("ARZAN_API_BASE", "").strip().rstrip("/")
        api_key = os.environ.get("ARZAN_API_KEY", "").strip()
        if not base_url:
            raise RuntimeError("ARZAN_API_BASE is not set")
        if not base_url.startswith("https://"):
            raise RuntimeError("ARZAN_API_BASE must use HTTPS")
        if not api_key:
            raise RuntimeError("ARZAN_API_KEY is not set")
        return cls(base_url=base_url, api_key=api_key)
