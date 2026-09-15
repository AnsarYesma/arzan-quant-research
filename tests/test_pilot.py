from datetime import date

import pytest

from arzan_quant.pilot import build_events, build_panel

duckdb = pytest.importorskip("duckdb")


def test_panel_and_change_screening():
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    con.execute("""CREATE TABLE observations AS SELECT
        id AS observation_id, ts::TIMESTAMPTZ AS observed_at, price,
        available AS is_available, 'KZT' AS currency, false AS is_promotion,
        NULL::DECIMAL AS regular_price, 'r' AS retailer_id, 's' AS store_id,
        'p' AS retailer_product_id, 'c' AS city_id, 'canonical' AS canonical_product_id,
        'manual' AS match_method, NULL::DOUBLE AS match_confidence
        FROM (VALUES
          ('1', '2026-08-02 12:00:00+00', 100, true),
          ('2', '2026-08-04 12:00:00+00', 110, true),
          ('9', '2026-08-05 12:00:00+00', 120, true),
          ('10', '2026-08-05 12:00:00+00', 130, true),
          ('11', '2026-08-06 12:00:00+00', 140, true),
          ('12', '2026-08-07 12:00:00+00', 150, false)
        ) t(id, ts, price, available)""")
    build_events(con)
    assert con.execute("SELECT observation_id FROM events WHERE clean_price_change").fetchall() == [
        ("2",)
    ]
    build_panel(con, date(2026, 8, 1), date(2026, 8, 8))
    rows = con.execute(
        "SELECT date, price, event_recorded_today, crawl_success_known FROM daily_panel ORDER BY date"
    ).fetchall()
    assert len(rows) == 6  # No fabricated state before the first event.
    assert rows[1] == (date(2026, 8, 3), 100, False, None)
    assert rows[3][1] == 130  # Numeric ID tie break, explicitly flagged as ambiguous.
    assert all(row[3] is None for row in rows)
    con.close()
