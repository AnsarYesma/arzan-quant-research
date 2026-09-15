"""Descriptive network, promotion persistence, and a fixed-base sample price index."""

from __future__ import annotations

from pathlib import Path

from .settings import ResearchSettings
from .warehouse import quote, rows


def price_index(con, cfg: ResearchSettings, weights: Path | None = None):
    category_filter = ""
    if cfg.grocery_categories:
        category_filter = (
            "AND category_id IN (" + ",".join(map(quote, cfg.grocery_categories)) + ")"
        )
    con.execute(f"""CREATE TABLE basket_candidates AS SELECT retailer_id, store_id,
        retailer_product_id, canonical_product_id, price AS base_price
        FROM panel WHERE date={quote(cfg.start)}::DATE AND state_eligible {category_filter}""")
    if weights is not None:
        con.read_parquet(str(weights)).create_view("_weights")
        required = {"retailer_id", "store_id", "retailer_product_id", "weight"}
        if required - {r[0] for r in con.execute("DESCRIBE _weights").fetchall()}:
            raise ValueError(
                "Basket weights need retailer_id, store_id, retailer_product_id, weight"
            )
        if con.execute(
            "SELECT count(*) FROM _weights WHERE weight IS NULL OR NOT isfinite(weight) OR weight<=0"
        ).fetchone()[0]:
            raise ValueError("Basket weights must be finite and positive")
        if con.execute("""SELECT count(*) FROM (SELECT retailer_id,store_id,retailer_product_id
            FROM _weights GROUP BY ALL HAVING count(*)>1)""").fetchone()[0]:
            raise ValueError("Duplicate basket weights")
        if con.execute("""SELECT count(*) FROM _weights w ANTI JOIN basket_candidates b
            USING(retailer_id,store_id,retailer_product_id)""").fetchone()[0]:
            raise ValueError("Every supplied basket weight needs an eligible opening price")
        con.execute("""CREATE TABLE basket AS SELECT b.*, w.weight/sum(w.weight) OVER() AS weight
            FROM basket_candidates b JOIN _weights w USING(retailer_id,store_id,retailer_product_id)""")
    else:
        # Equal weight to each observed canonical product, then equally across its offers.
        # Unlinked products receive their own source-offer identifier, never one NULL group.
        con.execute("""CREATE TABLE basket AS WITH weighted AS (
            SELECT *, 1.0/count(*) OVER(PARTITION BY coalesce(canonical_product_id,
                retailer_id || ':' || store_id || ':' || retailer_product_id)) AS raw_weight
            FROM basket_candidates)
            SELECT * EXCLUDE(raw_weight), raw_weight/sum(raw_weight) OVER() AS weight FROM weighted""")
    con.execute(f"""CREATE TABLE price_index AS
        WITH daily AS (
          SELECT p.date, count(*) AS basket_quotes,
            coalesce(sum(b.weight) FILTER(WHERE p.state_eligible),0) AS weight_coverage,
            sum(CASE WHEN p.state_eligible THEN b.weight*ln(p.price/b.base_price) END) AS weighted_log_relative,
            count(*) FILTER(WHERE p.state_eligible) AS eligible_quotes,
            coalesce(sum(b.weight) FILTER(WHERE p.state_eligible AND p.is_promotion),0) AS promotion_weight
          FROM panel p JOIN basket b USING(retailer_id,store_id,retailer_product_id)
          WHERE p.date>={quote(cfg.start)}::DATE GROUP BY p.date
        ) SELECT *, CASE WHEN weight_coverage>={cfg.min_index_weight_coverage}
            THEN 100*exp(weighted_log_relative/weight_coverage) END AS index_value
        FROM daily ORDER BY date""")
    result = rows(
        con,
        """SELECT count(*) AS days, count(index_value) AS published_days,
        min(weight_coverage) AS min_weight_coverage, max(index_value) AS max_index
        FROM price_index""",
    )[0]
    result.update(
        {
            "base_date": cfg.start,
            "basket_offers": con.execute("SELECT count(*) FROM basket").fetchone()[0],
            "label": "sample grocery price index"
            if cfg.grocery_categories
            else "unclassified sample price index",
            "weights": "supplied offer weights"
            if weights
            else "equal product, equal within-product offer",
            "method": "fixed-base geometric price relatives, available-weight renormalization",
            "limitation": "Not expenditure-weighted official CPI; missing quote composition can change.",
        }
    )
    return result


def descriptive_network(con):
    # Rate comparisons condition on observed target risk rows. They are not adjusted causal effects.
    return rows(
        con,
        """WITH baseline AS (SELECT retailer_id, avg(changed) AS baseline_rate,
          count(*) AS risk_rows FROM features GROUP BY retailer_id),
        edges AS (SELECT e.source_retailer, f.retailer_id AS target_retailer,
          count(*) AS exposed_risk_rows, avg(f.changed) AS exposed_change_rate,
          avg(f.magnitude) FILTER(WHERE f.changed=1) AS mean_target_mark,
          avg(e.mean_mark) AS mean_source_mark, avg(e.active_days) AS mean_source_active_days,
          avg(e.mean_lag_days) AS mean_exposure_lag_days
          FROM retailer_exposures e JOIN features f USING(row_id) GROUP BY ALL)
        SELECT e.*, b.baseline_rate, b.risk_rows,
          e.exposed_change_rate-b.baseline_rate AS rate_difference
        FROM edges e JOIN baseline b ON e.target_retailer=b.retailer_id
        ORDER BY exposed_risk_rows DESC""",
    )


def promotion_diagnostics(con, horizon=7):
    if type(horizon) is not int or horizon < 1:
        raise ValueError("horizon must be positive")
    return rows(
        con,
        f"""WITH changes AS (
          SELECT * FROM transitions WHERE outcome_eligible AND abs(log_return)>1e-10
        ), followed AS (
          SELECT a.retailer_id, a.store_id, a.retailer_product_id, a.date,
            a.is_promotion, a.promotion_transition, a.price, a.previous_price,
            count(*) FILTER(WHERE b.state_eligible) AS eligible_followup_days,
            max(b.price) FILTER(WHERE b.date=a.date+INTERVAL {horizon} DAY) AS horizon_price
          FROM changes a LEFT JOIN panel b ON a.retailer_id=b.retailer_id AND a.store_id=b.store_id
            AND a.retailer_product_id=b.retailer_product_id
            AND b.date>a.date AND b.date<=a.date+INTERVAL {horizon} DAY GROUP BY ALL
        ) SELECT retailer_id, is_promotion, promotion_transition, count(*) AS changes,
          count(*) FILTER(WHERE eligible_followup_days={horizon}) AS complete_followups,
          avg(cast(sign(horizon_price-previous_price)=sign(price-previous_price) AS INT))
            FILTER(WHERE eligible_followup_days={horizon}) AS fraction_same_direction_at_horizon
        FROM followed GROUP BY ALL ORDER BY retailer_id, is_promotion, promotion_transition""",
    )
