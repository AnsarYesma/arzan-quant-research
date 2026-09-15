import pytest

from arzan_quant.features import build_features
from arzan_quant.fixtures import generate_export
from arzan_quant.settings import ResearchSettings
from arzan_quant.warehouse import construct_panel, load_exports

duckdb = pytest.importorskip("duckdb")
pytest.importorskip("pyarrow")


def prepare(path, settings):
    con = duckdb.connect()
    load_exports(con, [path])
    construct_panel(con, settings)
    build_features(con, settings)
    return con


def test_exposures_use_only_past_and_exclude_feed_family(tmp_path):
    root = generate_export(tmp_path / "synthetic", days=80)
    cfg = ResearchSettings.read(root / "settings.json")
    con = prepare(root, cfg)
    # Independent derivation of the source dates for each exposure row.
    violations = con.execute("""SELECT count(*) FROM retailer_exposures e
        JOIN targets t USING(row_id) WHERE NOT EXISTS (SELECT 1 FROM shocks s
          WHERE s.retailer_id=e.source_retailer AND s.canonical_product_id=t.canonical_product_id
          AND s.city_id=t.city_id AND s.date<t.date AND s.date>=t.date-INTERVAL 3 DAY)""").fetchone()[
        0
    ]
    assert violations == 0
    assert con.execute("SELECT count(*) FROM retailer_exposures").fetchone()[0] > 0
    same = ResearchSettings(
        **(cfg.as_dict() | {"feed_groups": {"alpha": "all", "beta": "all", "gamma": "all"}})
    )
    con2 = prepare(root, same)
    assert con2.execute("SELECT count(*) FROM retailer_exposures").fetchone()[0] == 0


def test_appending_future_changes_cannot_alter_past_features(tmp_path):
    root = generate_export(tmp_path / "synthetic", days=80)
    cfg = ResearchSettings.read(root / "settings.json")
    con = prepare(root, cfg)
    columns = "* EXCLUDE(row_id)"
    expected = con.execute(
        f"SELECT {columns} FROM features WHERE date<'2025-02-01' ORDER BY ALL"
    ).fetchall()
    other = duckdb.connect()
    load_exports(other, [root])
    other.execute("UPDATE observations SET price=price*2 WHERE observed_at>='2025-02-01'")
    construct_panel(other, cfg)
    build_features(other, cfg)
    actual = other.execute(
        f"SELECT {columns} FROM features WHERE date<'2025-02-01' ORDER BY ALL"
    ).fetchall()
    assert actual == expected


def test_source_barcode_rule_is_independent_of_canonical_assignment(tmp_path):
    root = generate_export(tmp_path / "synthetic", days=80)
    cfg = ResearchSettings.read(root / "settings.json")
    con = prepare(root, cfg)
    assert con.execute("SELECT count(*) FROM retailer_exposures").fetchone()[0] > 0
    con.execute("UPDATE transitions SET barcodes=list_value(retailer_id)")
    build_features(con, cfg, matching="barcode")
    assert con.execute("SELECT count(*) FROM retailer_exposures").fetchone()[0] == 0


def test_duplicating_source_stores_does_not_multiply_kernel_exposure(tmp_path):
    root = generate_export(tmp_path / "synthetic", days=80)
    cfg = ResearchSettings.read(root / "settings.json")
    con = prepare(root, cfg)
    sql = """SELECT f.date,f.store_id,f.retailer_product_id,e.active_days,e.decayed_count
        FROM retailer_exposures e JOIN features f USING(row_id)
        WHERE e.source_retailer='alpha' AND f.retailer_id='beta' ORDER BY ALL"""
    before = con.execute(sql).fetchall()
    con.execute("""INSERT INTO transitions SELECT * REPLACE (store_id||'_duplicate' AS store_id)
        FROM transitions WHERE retailer_id='alpha'""")
    build_features(con, cfg)
    assert con.execute(sql).fetchall() == before


def test_sparse_feature_lookup_preserves_full_history_lags(tmp_path):
    root = generate_export(tmp_path / "synthetic", days=80)
    cfg = ResearchSettings.read(root / "settings.json")
    con = prepare(root, cfg)
    expected = con.execute("""WITH full_history AS (
        SELECT *, lag(is_promotion) OVER w AS expected_promotion,
          lag(log_return) OVER w AS expected_return,
          lag(state_age_days) OVER w AS expected_age,
          lag(date) OVER w AS expected_date
        FROM transitions WHERE match_eligible
        WINDOW w AS (PARTITION BY retailer_id,store_id,retailer_product_id ORDER BY date)
        ) SELECT retailer_id,store_id,retailer_product_id,date,
          coalesce(expected_promotion,false),coalesce(expected_return,0),expected_age
        FROM full_history WHERE outcome_eligible AND previous_match_eligible
          AND canonical_product_id=previous_canonical
          AND expected_date=date-INTERVAL 1 DAY ORDER BY ALL""").fetchall()
    actual = con.execute("""SELECT retailer_id,store_id,retailer_product_id,date,
        lag_promotion,lag_return,lag_state_age FROM features ORDER BY ALL""").fetchall()
    assert actual == expected
    assert (
        con.execute("SELECT count(*) FROM feature_base").fetchone()[0]
        < con.execute("SELECT count(*) FROM transitions WHERE match_eligible").fetchone()[0]
    )


def test_preaggregated_category_context_matches_direct_temporal_join(tmp_path):
    root = generate_export(tmp_path / "context", days=100)
    cfg = ResearchSettings.read(root / "settings.json")
    con = duckdb.connect()
    load_exports(con, [root])
    construct_panel(con, cfg)
    # Exercise distinct and NULL category identities rather than only one group.
    con.execute("""UPDATE transitions SET category_id=CASE
        WHEN retailer_id='alpha' THEN NULL
        WHEN retailer_id='beta' THEN 'other' ELSE category_id END""")
    build_features(con, cfg)
    expected = con.execute("""SELECT t.row_id,
        greatest(coalesce(sum(s.activity) FILTER(WHERE s.category_id=t.category_id),0)
          -coalesce(p.same_product_count,0),0) AS category_count,
        coalesce(sum(s.activity) FILTER(WHERE s.category_id<>t.category_id),0) AS cross_category_count
        FROM targets t LEFT JOIN category_activity s ON s.date<t.date
          AND s.date>=t.date-INTERVAL 3 DAY AND s.city_id=t.city_id
        LEFT JOIN product_context p USING(row_id)
        GROUP BY t.row_id,p.same_product_count ORDER BY t.row_id""").fetchall()
    actual = con.execute("""SELECT row_id,category_count,cross_category_count
        FROM contextual_exposures ORDER BY row_id""").fetchall()
    assert actual == expected
    con.close()
