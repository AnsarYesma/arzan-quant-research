import pytest

from arzan_quant.api import ApiProtocolError, ResearchApiClient
from arzan_quant.config import ApiConfig


class FakeClient(ResearchApiClient):
    def __init__(self, pages: list[dict[str, object]]) -> None:
        super().__init__(ApiConfig("https://example.invalid", "secret"))
        self.pages = iter(pages)

    def get_page(self, endpoint: str, params: dict[str, object]) -> dict[str, object]:
        return next(self.pages)


def test_cursor_pagination() -> None:
    client = FakeClient(
        [
            {"items": [{"id": 1}], "has_more": True, "next_cursor": "abc"},
            {"items": [{"id": 2}], "has_more": False, "next_cursor": None},
        ]
    )
    assert list(client.iter_items("products", {})) == [{"id": 1}, {"id": 2}]


def test_repeated_cursor_is_rejected() -> None:
    client = FakeClient(
        [
            {"items": [], "has_more": True, "next_cursor": "abc"},
            {"items": [], "has_more": True, "next_cursor": "abc"},
        ]
    )
    with pytest.raises(ApiProtocolError, match="repeated a cursor"):
        list(client.iter_items("products", {}))
