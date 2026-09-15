from datetime import UTC, datetime, timedelta

import pytest

from arzan_quant.fixtures import write_export
from arzan_quant.settings import ResearchSettings
from arzan_quant.warehouse import construct_panel, load_exports

duckdb = pytest.importorskip("duckdb")
pytest.importorskip("pyarrow")


def event(id, day, price=100, **updates):
    row = {
        "observation_id": str(id),
        "observed_at": datetime(2026, 8, 1, tzinfo=UTC) + timedelta(days=day),
        "retailer_id": "r",
        "store_id": "s",
        "retailer_product_id": "p",
        "city_id": "c",
        "price": price,
        "regular_price": None,
        "is_available": True,
        "is_promotion": False,
        "currency": "KZT",
        "canonical_product_id": "product",
        "match_method": "manual",
        "match_confidence": 1.0,
    }
    return row | updates


def export(tmp_path, name, records, coverage=None, cutoff=None):
    return write_export(
        tmp_path / name, records, coverage or [], name, cutoff or datetime(2026, 9, 1, tzinfo=UTC)
    )


def test_overlap_is_deduplicated_and_market_conflicts_fail(tmp_path):
    a = export(tmp_path, "a", [event(1, 0)])
    b = export(tmp_path, "b", [event(1, 0), event(2, 1, 110)])
    con = duckdb.connect()
    assert load_exports(con, [a, b])["observations"] == 2
    c = export(tmp_path, "c", [event(1, 0, 999)])
    with pytest.raises(ValueError, match="Conflicting market"):
        load_exports(duckdb.connect(), [a, c])


def test_latest_metadata_revision_wins_regardless_input_order(tmp_path):
    a = export(tmp_path, "a", [event(1, 0, canonical_product_id="old")])
    b = export(
        tmp_path,
        "b",
        [event(1, 0, canonical_product_id="new")],
        cutoff=datetime(2026, 10, 1, tzinfo=UTC),
    )
    for inputs in ([a, b], [b, a]):
        con = duckdb.connect()
        load_exports(con, inputs)
        assert con.execute("SELECT canonical_product_id FROM observations").fetchone()[0] == "new"


def test_opening_state_outage_invalid_price_and_mapping_gate(tmp_path):
    coverage = [
        {
            "retailer_id": "r",
            "store_id": "s",
            "date": datetime(2026, 8, d, tzinfo=UTC).date(),
            "crawl_status": "failed" if d == 3 else "successful",
            "is_complete_utc_day": True,
        }
        for d in range(1, 7)
    ]
    root = export(
        tmp_path,
        "data",
        [event(1, -2), event(2, 1, 110), event(3, 3, 120), event(4, 4, 0), event(5, 5, 125)],
        coverage,
    )
    con = duckdb.connect()
    load_exports(con, [root])
    cfg = ResearchSettings("2026-08-01", "2026-08-07", assume_store_success_confirms_state=True)
    construct_panel(con, cfg)
    values = con.execute(
        "SELECT price, outcome_eligible, match_eligible FROM transitions ORDER BY date"
    ).fetchall()
    assert [r[0] for r in values] == [100, 110, 110, 120, 0, 125]
    assert [r[1] for r in values] == [False, True, False, False, False, False]
    assert all(not r[2] for r in values)  # Frozen canonical assignment is not historical validity.


def test_silence_is_not_an_observed_zero(tmp_path):
    root = export(tmp_path, "data", [event(1, 0), event(2, 2, 110)])
    con = duckdb.connect()
    load_exports(con, [root])
    construct_panel(con, ResearchSettings("2026-08-01", "2026-08-05"))
    assert con.execute("SELECT count(*) FROM transitions WHERE outcome_eligible").fetchone()[0] == 0


def test_invalid_settings_rejected():
    with pytest.raises(ValueError):
        ResearchSettings("2026-09-01", "2026-08-01")
    with pytest.raises(ValueError):
        ResearchSettings("2026-08-01", "2026-09-01", assume_store_success_confirms_state="yes")


def test_naive_parquet_timestamps_are_not_silently_assumed_utc(tmp_path):
    record = event(1, 0)
    record["observed_at"] = record["observed_at"].replace(tzinfo=None)
    root = export(tmp_path, "naive", [record])
    with pytest.raises(ValueError, match="timezone-aware"):
        load_exports(duckdb.connect(), [root])


def test_separate_opening_file_and_future_opening_rejection(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    root = export(tmp_path, "data", [event(2, 1, 110)])
    opening = tmp_path / "opening.parquet"
    pq.write_table(pa.Table.from_pylist([event(1, -1, 100)]), opening)
    con = duckdb.connect()
    load_exports(con, [root], opening)
    construct_panel(con, ResearchSettings("2026-08-01", "2026-08-04"))
    assert con.execute("SELECT price FROM panel WHERE date='2026-08-01'").fetchone()[0] == 100
    future = tmp_path / "future.parquet"
    pq.write_table(pa.Table.from_pylist([event(3, 2, 120)]), future)
    con = duckdb.connect()
    load_exports(con, [root], future)
    with pytest.raises(ValueError, match="Opening states"):
        construct_panel(con, ResearchSettings("2026-08-01", "2026-08-04"))


def test_continuous_observation_includes_quiet_days_and_next_price_change(tmp_path):
    # No event for ten days means an unchanged price under continuous coverage,
    # rather than ten missing observations. The age of the last change is not staleness.
    root = export(tmp_path, "continuous", [event(1, 0), event(2, 10, 110)])
    con = duckdb.connect()
    load_exports(con, [root])
    construct_panel(
        con, ResearchSettings("2026-08-01", "2026-08-13", assume_continuous_observation=True)
    )
    actual = con.execute(
        "SELECT date,outcome_eligible,log_return FROM transitions ORDER BY date"
    ).fetchall()
    assert actual[0][1] is False  # No invented pre-entry opening price.
    assert all(row[1] for row in actual[1:])
    assert sum(abs(row[2]) > 1e-10 for row in actual[1:]) == 1
    assert actual[10][2] == pytest.approx(__import__("math").log(1.1))


def test_continuous_observation_still_respects_outages_and_unavailability(tmp_path):
    coverage = [
        {
            "retailer_id": "r",
            "store_id": "s",
            "date": datetime(2026, 8, 3, tzinfo=UTC).date(),
            "crawl_status": "failed",
            "is_complete_utc_day": True,
        }
    ]
    root = export(
        tmp_path,
        "outage",
        [event(1, 0), event(2, 4, is_available=False), event(3, 6, 110)],
        coverage,
    )
    con = duckdb.connect()
    load_exports(con, [root])
    construct_panel(
        con, ResearchSettings("2026-08-01", "2026-08-09", assume_continuous_observation=True)
    )
    actual = con.execute(
        "SELECT state_eligible,outcome_eligible FROM transitions ORDER BY date"
    ).fetchall()
    assert actual == [
        (True, False),
        (True, True),
        (False, False),
        (True, False),
        (False, False),
        (False, False),
        (True, False),
        (True, True),
    ]
    with pytest.raises(ValueError, match="must be boolean"):
        ResearchSettings("2026-08-01", "2026-08-09", assume_continuous_observation="yes")
