from datetime import UTC, datetime

import pytest

duckdb = pytest.importorskip("duckdb")
pytest.importorskip("pyarrow")
from test_warehouse import event, export

from arzan_quant.analytics import price_index, promotion_diagnostics
from arzan_quant.settings import ResearchSettings
from arzan_quant.warehouse import construct_panel, load_exports


def test_fixed_basket_index_and_coverage_gate(tmp_path):
    records = [event(1, 0, 100), event(2, 1, 110), event(3, 2, 0)]
    coverage = [
        {
            "retailer_id": "r",
            "store_id": "s",
            "date": datetime(2026, 8, d, tzinfo=UTC).date(),
            "crawl_status": "successful",
            "is_complete_utc_day": True,
        }
        for d in range(1, 5)
    ]
    root = export(tmp_path, "data", records, coverage)
    con = duckdb.connect()
    load_exports(con, [root])
    cfg = ResearchSettings("2026-08-01", "2026-08-05", assume_store_success_confirms_state=True)
    construct_panel(con, cfg)
    result = price_index(con, cfg)
    assert result["basket_offers"] == 1
    values = con.execute("SELECT index_value FROM price_index ORDER BY date").fetchall()
    assert values[0][0] == pytest.approx(100)
    assert values[1][0] == pytest.approx(110)
    assert values[2][0] is None and values[3][0] is None
    assert result["min_weight_coverage"] == 0
    promotion = promotion_diagnostics(con, horizon=2)
    assert promotion[0]["complete_followups"] == 0  # Invalid future state is censored.
