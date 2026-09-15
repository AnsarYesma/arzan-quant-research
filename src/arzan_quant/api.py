from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import ApiConfig


class ApiProtocolError(RuntimeError):
    """Raised when a response violates cursor or envelope expectations."""


class ResearchApiClient:
    def __init__(self, config: ApiConfig, timeout_seconds: float = 60.0) -> None:
        self.config = config
        self.timeout_seconds = timeout_seconds

    def get_page(self, endpoint: str, params: Mapping[str, Any]) -> dict[str, Any]:
        clean_params = {key: value for key, value in params.items() if value is not None}
        url = f"{self.config.base_url}/{endpoint.lstrip('/')}?{urlencode(clean_params)}"
        request = Request(
            url,
            method="GET",
            headers={
                "Authorization": f"ApiKey {self.config.api_key}",
                "Accept": "application/json",
                "User-Agent": "arzan-quant-research/0.1",
            },
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.load(response)
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise ApiProtocolError("response must contain an items list")
        return payload

    def iter_items(self, endpoint: str, params: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
        cursor: str | None = None
        seen_cursors: set[str] = set()

        while True:
            page_params = dict(params)
            if cursor is not None:
                page_params["cursor"] = cursor
            page = self.get_page(endpoint, page_params)
            yield from page["items"]

            next_cursor = page.get("next_cursor")
            has_more = bool(page.get("has_more"))
            if not has_more:
                if next_cursor is not None:
                    raise ApiProtocolError("next_cursor must be null when has_more is false")
                return
            if not isinstance(next_cursor, str) or not next_cursor:
                raise ApiProtocolError("has_more requires a non-empty next_cursor")
            if next_cursor in seen_cursors:
                raise ApiProtocolError("server repeated a cursor; refusing an infinite loop")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
