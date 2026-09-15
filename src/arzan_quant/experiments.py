"""Exploratory response-timing and coarse-grained excitation experiments."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .evaluation import feature_frame
from .models import Encoder, calibration, fit_glm, metrics, predict_glm
from .settings import ResearchSettings
from .warehouse import rows


def timestamp_audit(con) -> dict:
    """Describe whether collection timestamps can support continuous-time claims."""
    result = rows(
        con,
        """WITH ordered AS (
          SELECT observed_at, price, lag(price) OVER (
            PARTITION BY retailer_id,store_id,retailer_product_id ORDER BY observed_at,observation_id
          ) AS prior_price
          FROM observations WHERE price>0 AND is_available
        ), changes AS (
          SELECT observed_at FROM ordered WHERE prior_price>0 AND price<>prior_price
        ) SELECT count(*) AS price_change_events,
          count(DISTINCT cast(observed_at AT TIME ZONE 'UTC' AS TIME)) AS distinct_times_of_day,
          count(DISTINCT date_trunc('minute', observed_at)) AS distinct_event_minutes,
          avg(cast(cast(observed_at AT TIME ZONE 'UTC' AS TIME)=TIME '00:00:00'
            AS DOUBLE)) AS midnight_share,
          min(observed_at) AS first_event, max(observed_at) AS last_event
        FROM changes""",
    )[0]
    events = result["price_change_events"]
    distinct = result["distinct_times_of_day"]
    result["supports_continuous_time_hawkes"] = bool(events and distinct >= min(100, events * 0.05))
    result["interpretation"] = (
        "timestamps show useful within-day variation; collection time may still differ from change time"
        if result["supports_continuous_time_hawkes"]
        else "timestamp resolution is too coarse for a defensible continuous-time Hawkes fit"
    )
    return result


def response_timing(con) -> dict:
    """Estimate descriptive lag profiles after isolated peer events."""
    con.execute("DROP TABLE IF EXISTS response_timing_rows")
    con.execute("""CREATE TEMP TABLE response_timing_rows AS
        WITH linked AS (
          SELECT row_id,lag_days,count(*) AS source_events,avg(mark) AS peer_mark
          FROM peer_daily_source WHERE lag_days<=14 GROUP BY row_id,lag_days
        ), joined AS (
          SELECT l.*,t.date,t.retailer_id,t.category_id,
            cast(abs(t.log_return)>1e-10 AS INT) AS changed,t.log_return,
            avg(cast(abs(t.log_return)>1e-10 AS DOUBLE)) OVER (
              PARTITION BY t.date,t.retailer_id,t.category_id) AS calendar_group_rate
          FROM linked l JOIN targets t USING(row_id)
        ) SELECT *, changed-calendar_group_rate AS calendar_group_residual,
          cast(changed=1 AND sign(log_return)=sign(peer_mark) AS INT) AS direction_agrees
        FROM joined""")
    overall = rows(
        con,
        """SELECT lag_days,count(*) AS target_days,sum(changed) AS changes,
          avg(changed) AS response_rate,avg(calendar_group_residual) AS adjusted_rate_difference,
          avg(direction_agrees) FILTER(WHERE changed=1 AND peer_mark<>0) AS directional_agreement,
          sum(cast(source_events>1 AS INTEGER)) AS overlapping_target_days
        FROM response_timing_rows GROUP BY lag_days ORDER BY lag_days""",
    )
    isolated = rows(
        con,
        """SELECT lag_days,count(*) AS target_days,avg(changed) AS response_rate,
          avg(calendar_group_residual) AS adjusted_rate_difference
        FROM response_timing_rows WHERE source_events=1
        GROUP BY lag_days ORDER BY lag_days""",
    )
    heterogeneity = rows(
        con,
        """SELECT retailer_id,category_id,lag_days,count(*) AS target_days,
          avg(changed) AS response_rate,avg(calendar_group_residual) AS adjusted_rate_difference
        FROM response_timing_rows GROUP BY ALL HAVING count(*)>=30
        ORDER BY target_days DESC,retailer_id,category_id,lag_days LIMIT 500""",
    )
    time_to_change = rows(
        con,
        """WITH episodes AS (
          SELECT p.source_retailer,p.source_date,t.retailer_id,t.store_id,
            t.retailer_product_id,t.category_id,sign(avg(p.mark)) AS source_direction,
            CASE WHEN min(p.lag_days)=1 AND count(DISTINCT p.lag_days)=max(p.lag_days)
              THEN max(p.lag_days) ELSE 0 END AS observed_through_day,
            min(p.lag_days) FILTER(WHERE abs(t.log_return)>1e-10) AS next_change_day
          FROM peer_daily_source p JOIN targets t USING(row_id)
          GROUP BY p.source_retailer,p.source_date,t.retailer_id,t.store_id,
            t.retailer_product_id,t.category_id
        ) SELECT h.horizon,source_direction,count(*) AS observable_episodes,
          avg(cast(CASE WHEN next_change_day<=h.horizon THEN 1 ELSE 0 END AS DOUBLE))
            AS cumulative_change_probability
        FROM episodes CROSS JOIN range(1,15) h(horizon)
        WHERE observed_through_day>=h.horizon
        GROUP BY h.horizon,source_direction ORDER BY h.horizon,source_direction""",
    )
    return {
        "status": "descriptive_association_only",
        "horizon_days": 14,
        "overall": overall,
        "isolated_events": isolated,
        "heterogeneity": heterogeneity,
        "time_to_next_change": time_to_change,
        "adjustment": "retailer-category-date mean; isolated table excludes overlapping source events",
    }


def focused_binned_excitation(con, cfg: ResearchSettings, max_products: int = 100) -> dict:
    """Compare binned Poisson models on frequently repriced multi-retailer products."""
    con.execute("DROP TABLE IF EXISTS excitation_products")
    con.execute(
        f"""CREATE TEMP TABLE excitation_products AS
        SELECT canonical_product_id,count(*) AS risk_days,
          count(*) FILTER(WHERE abs(log_return)>1e-10) AS changes,
          count(DISTINCT retailer_id) AS retailers
        FROM targets GROUP BY canonical_product_id
        HAVING count(DISTINCT retailer_id)>=2 AND changes>=10
        ORDER BY changes DESC LIMIT {int(max_products)}"""
    )
    selected = rows(
        con,
        """SELECT count(*) AS products,coalesce(sum(risk_days),0) AS risk_days,
          coalesce(sum(changes),0) AS changes,min(retailers) AS minimum_retailers
        FROM excitation_products""",
    )[0]
    frame = feature_frame(
        con, "WHERE canonical_product_id IN (SELECT canonical_product_id FROM excitation_products)"
    )
    frame["date"] = pd.to_datetime(frame["date"])
    folds = []
    boundary = date.fromisoformat(cfg.start) + timedelta(days=cfg.min_train_days)
    end = date.fromisoformat(cfg.end)
    while boundary < end:
        test_end = min(end, boundary + timedelta(days=cfg.test_days))
        train = frame[frame.date < pd.Timestamp(boundary)]
        test = frame[(frame.date >= pd.Timestamp(boundary)) & (frame.date < pd.Timestamp(test_end))]
        fold = {"train_end_exclusive": str(boundary), "test_end_exclusive": str(test_end)}
        if len(test) == 0 or train.changed.sum() < cfg.min_train_events:
            fold.update({"status": "insufficient_data", "metrics": {}})
        else:
            y = test.changed.to_numpy(float)
            fold.update({"status": "evaluated", "metrics": {}, "calibration": {}})
            for name, excitation in (("time_varying_baseline", False), ("cross_retailer_excitation", True)):
                encoder = Encoder.fit(train, diffusion=excitation)
                x_train = encoder.transform(train, sparse_output=True)
                x_test = encoder.transform(test, sparse_output=True)
                beta, diagnostic = fit_glm(x_train, train.changed.to_numpy(float), "poisson")
                probability = predict_glm(x_test, beta, "poisson")
                fold["metrics"][name] = metrics(
                    y, probability, test.magnitude.to_numpy(float), np.zeros(len(test))
                )
                fold["calibration"][name] = calibration(y, probability)
                fold.setdefault("diagnostics", {})[name] = diagnostic
        folds.append(fold)
        boundary = test_end
    aggregate = {}
    for fold in folds:
        for name, score in fold.get("metrics", {}).items():
            total = aggregate.setdefault(name, {key: 0 for key in score})
            for key, value in score.items():
                total[key] += (
                    value
                    if key in ("n", "events")
                    else score["n"] * (value**2 if key == "return_rmse" else value)
                )
    for score in aggregate.values():
        for key in score:
            if key not in ("n", "events"):
                score[key] /= score["n"]
                if key == "return_rmse":
                    score[key] = float(np.sqrt(score[key]))
    return {
        "status": "evaluated" if aggregate else "insufficient_data",
        "model_kind": "coarse_grained_daily_poisson_excitation; not continuous-time Hawkes",
        "selection": selected,
        "primary_metric": "brier",
        "folds": folds,
        "aggregate": aggregate,
    }
