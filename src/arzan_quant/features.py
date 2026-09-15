"""Past-only feature construction; each row predicts a UTC day's state change."""

from __future__ import annotations

from .settings import ResearchSettings
from .warehouse import rows


def build_features(
    con,
    cfg: ResearchSettings,
    matching: str = "confidence",
    exclude_promotions: bool = False,
    max_age_days: int | None = None,
) -> dict:
    if matching not in ("confidence", "barcode"):
        raise ValueError("matching must be confidence or barcode")
    if max_age_days is not None and (type(max_age_days) is not int or max_age_days < 1):
        raise ValueError("max_age_days must be a positive integer")
    for table in (
        "feed_groups",
        "feature_base",
        "targets",
        "shocks",
        "peer_daily_source",
        "retailer_exposures",
        "daily_peer_prices",
        "competitor_context",
        "own_history",
        "group_activity",
        "category_activity",
        "contextual_exposures",
        "product_context",
        "rolling_category_activity",
        "rolling_city_activity",
        "features",
    ):
        con.execute(f"DROP TABLE IF EXISTS {table}")
    con.execute("CREATE TABLE feed_groups(retailer_id VARCHAR, family VARCHAR)")
    if cfg.feed_groups:
        con.executemany("INSERT INTO feed_groups VALUES (?, ?)", list(cfg.feed_groups.items()))
    # Only eligible outcome rows can become targets or shocks. Join the prior
    # calendar day before projecting them; do not sort/copy every carried state.
    # Missing prior rows remain NULL, preserving the opening-day target gate.
    con.execute("""CREATE TABLE feature_base AS
        SELECT t.retailer_id, t.store_id, t.retailer_product_id, t.date,
          t.canonical_product_id, t.city_id, t.category_id, t.barcodes,
          t.unit, t.quantity, t.pack_count, t.price, t.previous_price,
          t.log_return, t.state_age_days,
          t.outcome_eligible, t.match_eligible, t.previous_match_eligible,
          t.previous_canonical, t.is_promotion, t.previous_promotion,
          coalesce(g.family, t.retailer_id) AS feed_family,
          coalesce(p.is_promotion, false) AS lag_promotion,
          p.log_return AS lag_return, p.state_age_days AS lag_state_age,
          p.date AS lag_date,
          row_number() OVER (ORDER BY t.date, t.retailer_id, t.store_id,
            t.retailer_product_id) AS row_id
        FROM transitions t LEFT JOIN feed_groups g USING(retailer_id)
        LEFT JOIN transitions p ON p.retailer_id=t.retailer_id
          AND p.store_id=t.store_id AND p.retailer_product_id=t.retailer_product_id
          AND p.date=t.date-INTERVAL 1 DAY AND p.match_eligible
        WHERE t.match_eligible AND t.outcome_eligible""")
    # Only use a mapping when it was also eligible at the forecast origin.
    con.execute(f"""CREATE TABLE targets AS SELECT * FROM feature_base
        WHERE outcome_eligible AND match_eligible AND previous_match_eligible
          AND canonical_product_id = previous_canonical
          AND lag_date = date - INTERVAL 1 DAY
          {f"AND state_age_days<={int(max_age_days)} AND lag_state_age<={int(max_age_days)}" if max_age_days is not None else ""}
          {"AND NOT is_promotion AND NOT previous_promotion" if exclude_promotions else ""}""")
    con.execute(f"""CREATE TABLE shocks AS SELECT * FROM feature_base
        WHERE outcome_eligible AND match_eligible AND abs(log_return)>1e-10
          AND previous_match_eligible AND canonical_product_id=previous_canonical
          {f"AND state_age_days<={int(max_age_days)} AND lag_state_age<={int(max_age_days)}" if max_age_days is not None else ""}
          {"AND NOT is_promotion AND NOT previous_promotion" if exclude_promotions else ""}""")
    exact = "AND list_has_any(t.barcodes, s.barcodes)" if matching == "barcode" else ""
    # Keep the configured exposure intact for the original features, while also
    # retaining fixed 1/3/7/14-day summaries for the pre-registered comparison.
    max_exposure = max(cfg.exposure_days, 14)
    con.execute(f"""CREATE TABLE peer_daily_source AS
        SELECT t.row_id, s.retailer_id AS source_retailer, s.date AS source_date,
          date_diff('day', s.date, t.date) AS lag_days, avg(s.log_return) AS mark
        FROM targets t JOIN shocks s ON s.date < t.date
          AND s.date >= t.date - INTERVAL {max_exposure} DAY
          AND s.canonical_product_id=t.canonical_product_id AND s.city_id=t.city_id
          AND s.feed_family <> t.feed_family
          AND s.unit=t.unit AND s.quantity=t.quantity AND s.pack_count=t.pack_count
          AND t.quantity>0 AND t.pack_count>0 {exact}
        GROUP BY t.row_id, s.retailer_id, s.date, t.date""")
    con.execute(f"""CREATE TABLE retailer_exposures AS
        SELECT row_id, source_retailer, count(*) AS active_days, avg(mark) AS mean_mark,
          sum(exp(-lag_days)) AS decayed_count, avg(lag_days) AS mean_lag_days
        FROM peer_daily_source WHERE lag_days<={cfg.exposure_days}
        GROUP BY row_id, source_retailer""")
    # Prices are taken from the day before the target. The target price and target
    # return are never used, so the price-gap predictors are available at forecast time.
    con.execute("""CREATE TABLE daily_peer_prices AS
        SELECT date,canonical_product_id,city_id,feed_family,unit,quantity,pack_count,
          min(price) AS minimum_price,avg(price) AS mean_price,count(*) AS offers
        FROM feature_base WHERE price>0 GROUP BY ALL""")
    con.execute("""CREATE TABLE competitor_context AS
        SELECT t.row_id, min(s.minimum_price) AS cheapest_peer_price,
          sum(s.mean_price*s.offers)/sum(s.offers) AS mean_peer_price,
          count(*) AS peer_families
        FROM targets t JOIN daily_peer_prices s
          ON s.date=t.date-INTERVAL 1 DAY
          AND s.canonical_product_id=t.canonical_product_id AND s.city_id=t.city_id
          AND s.feed_family<>t.feed_family AND s.unit=t.unit
          AND s.quantity=t.quantity AND s.pack_count=t.pack_count
        GROUP BY t.row_id""")
    con.execute("""CREATE TABLE own_history AS
        SELECT row_id,
          date_diff('day', max(CASE WHEN abs(log_return)>1e-10 THEN date END) OVER prior,
            date) AS days_since_own_change,
          avg(cast(abs(log_return)>1e-10 AS DOUBLE)) OVER last7 AS own_change_rate_7d,
          avg(cast(abs(log_return)>1e-10 AS DOUBLE)) OVER last30 AS own_change_rate_30d,
          avg(cast(abs(log_return)>1e-10 AS DOUBLE)) OVER last90 AS own_change_rate_90d
        FROM targets
        WINDOW prior AS (PARTITION BY retailer_id,store_id,retailer_product_id
            ORDER BY date ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),
          last7 AS (PARTITION BY retailer_id,store_id,retailer_product_id
            ORDER BY date RANGE BETWEEN INTERVAL 7 DAY PRECEDING AND INTERVAL 1 DAY PRECEDING),
          last30 AS (PARTITION BY retailer_id,store_id,retailer_product_id
            ORDER BY date RANGE BETWEEN INTERVAL 30 DAY PRECEDING AND INTERVAL 1 DAY PRECEDING),
          last90 AS (PARTITION BY retailer_id,store_id,retailer_product_id
            ORDER BY date RANGE BETWEEN INTERVAL 90 DAY PRECEDING AND INTERVAL 1 DAY PRECEDING)""")
    # Aggregate source activity before temporal joins to prevent many-to-many blowups.
    con.execute("""CREATE TABLE group_activity AS
        SELECT date, retailer_id, feed_family, city_id, category_id, canonical_product_id,
          unit, quantity, pack_count,
          avg(log_return) AS mark, count(*) AS n
        FROM shocks GROUP BY ALL""")
    con.execute("""CREATE TABLE category_activity AS
        SELECT date, city_id, category_id, count(*) AS activity FROM group_activity GROUP BY ALL""")
    # Materialize independently so simultaneous large hash aggregates do not
    # exhaust the bounded warehouse memory. Category activity is shared across
    # targets and can be summed before joining individual offers.
    con.execute(f"""CREATE TABLE product_context AS
        SELECT t.row_id,
          count(*) FILTER (WHERE s.canonical_product_id=t.canonical_product_id
            AND s.city_id<>t.city_id AND s.retailer_id=t.retailer_id
            AND s.unit=t.unit AND s.quantity=t.quantity AND s.pack_count=t.pack_count) AS cross_city_count,
          count(*) FILTER (WHERE s.category_id=t.category_id AND s.city_id=t.city_id
            AND s.canonical_product_id=t.canonical_product_id) AS same_product_count
        FROM targets t JOIN group_activity s ON s.date<t.date
          AND s.date>=t.date - INTERVAL {cfg.exposure_days} DAY
          AND s.canonical_product_id=t.canonical_product_id GROUP BY t.row_id""")
    con.execute(f"""CREATE TABLE rolling_category_activity AS
        SELECT cast(s.date + cast(d.lag AS INTEGER) AS DATE) AS date,
          s.city_id, s.category_id, sum(s.activity) AS activity
        FROM category_activity s CROSS JOIN range(1, {cfg.exposure_days + 1}) d(lag)
        GROUP BY ALL""")
    con.execute("""CREATE TABLE rolling_city_activity AS
        SELECT date, city_id, sum(activity) FILTER(WHERE category_id IS NOT NULL) AS activity
        FROM rolling_category_activity GROUP BY ALL""")
    con.execute("""CREATE TABLE contextual_exposures AS
        SELECT t.row_id, coalesce(p.cross_city_count,0) AS cross_city_count,
          greatest(coalesce(c.activity,0)-coalesce(p.same_product_count,0),0) AS category_count,
          CASE WHEN t.category_id IS NULL THEN 0
            ELSE coalesce(a.activity,0)-coalesce(c.activity,0) END AS cross_category_count
        FROM targets t LEFT JOIN product_context p USING(row_id)
        LEFT JOIN rolling_category_activity c
          ON c.date=t.date AND c.city_id=t.city_id AND c.category_id=t.category_id
        LEFT JOIN rolling_city_activity a ON a.date=t.date AND a.city_id=t.city_id""")
    con.execute("""CREATE TABLE features AS
        SELECT t.row_id, t.date, t.retailer_id, t.store_id, t.retailer_product_id,
          t.canonical_product_id, t.city_id, t.category_id,
          cast(abs(t.log_return)>1e-10 AS INT) AS changed, t.log_return AS magnitude,
          t.lag_promotion, coalesce(t.lag_return, 0) AS lag_return, t.lag_state_age,
          dayofweek(t.date) AS day_of_week,
          coalesce(r.peer_active_days, 0) AS peer_active_days,
          coalesce(r.peer_mark, 0) AS peer_mark,
          coalesce(r.decayed_count, 0) AS peer_decay,
          coalesce(x.peer_active_1d, 0) AS peer_active_1d,
          coalesce(x.peer_active_3d, 0) AS peer_active_3d,
          coalesce(x.peer_active_7d, 0) AS peer_active_7d,
          coalesce(x.peer_active_14d, 0) AS peer_active_14d,
          coalesce(h.days_since_own_change, 3650) AS days_since_own_change,
          coalesce(h.own_change_rate_7d, 0) AS own_change_rate_7d,
          coalesce(h.own_change_rate_30d, 0) AS own_change_rate_30d,
          coalesce(h.own_change_rate_90d, 0) AS own_change_rate_90d,
          CASE WHEN p.cheapest_peer_price>0
            THEN ln(t.previous_price/p.cheapest_peer_price) ELSE 0 END AS cheapest_peer_log_gap,
          CASE WHEN p.mean_peer_price>0
            THEN ln(t.previous_price/p.mean_peer_price) ELSE 0 END AS mean_peer_log_gap,
          cast(p.cheapest_peer_price IS NOT NULL
            AND t.previous_price<=p.cheapest_peer_price AS INT) AS was_cheapest,
          coalesce(p.peer_families, 0) AS priced_peer_families,
          coalesce(c.cross_city_count, 0) AS cross_city_count,
          coalesce(c.category_count, 0) AS category_count,
          coalesce(c.cross_category_count, 0) AS cross_category_count
        FROM targets t LEFT JOIN (
          SELECT row_id, sum(active_days) AS peer_active_days, avg(mean_mark) AS peer_mark,
            sum(decayed_count) AS decayed_count FROM retailer_exposures GROUP BY row_id
        ) r USING(row_id) LEFT JOIN (
          SELECT row_id,
            count(*) FILTER(WHERE lag_days<=1) AS peer_active_1d,
            count(*) FILTER(WHERE lag_days<=3) AS peer_active_3d,
            count(*) FILTER(WHERE lag_days<=7) AS peer_active_7d,
            count(*) FILTER(WHERE lag_days<=14) AS peer_active_14d
          FROM peer_daily_source GROUP BY row_id
        ) x USING(row_id) LEFT JOIN own_history h USING(row_id)
        LEFT JOIN competitor_context p USING(row_id)
        LEFT JOIN contextual_exposures c USING(row_id)""")
    summary = rows(
        con,
        """SELECT count(*) AS rows, sum(changed) AS changes,
        min(date) AS first_date, max(date) AS last_date FROM features""",
    )[0]
    summary.update(
        {
            "matching": matching,
            "exclude_promotions": exclude_promotions,
            "mapping_mode": "retrospective"
            if cfg.retrospective_mapping
            else "historical_validity_only",
            "window_days": cfg.exposure_days,
            "comparison_lag_days": [1, 3, 7, 14],
        }
    )
    summary["max_state_age_days_override"] = max_age_days
    return summary
