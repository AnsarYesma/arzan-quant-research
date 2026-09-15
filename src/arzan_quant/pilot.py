"""Reproducible private pilot profiling; requires the `data` dependency group."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from .manifest import sha256_file, verify_manifest


def literal(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def build_events(con) -> None:
    con.execute("""
        CREATE TABLE events AS
        WITH ordered AS (
          SELECT *,
            count(*) OVER (PARTITION BY retailer_id, store_id, retailer_product_id,
              observed_at) AS timestamp_multiplicity,
            lag(price) OVER w AS previous_price,
            lag(is_available) OVER w AS previous_available,
            lag(observed_at) OVER w AS previous_observed_at,
            lag(is_promotion) OVER w AS previous_promotion,
            lag(currency) OVER w AS previous_currency,
            lag(canonical_product_id) OVER w AS previous_canonical_product_id
          FROM observations
          WINDOW w AS (PARTITION BY retailer_id, store_id, retailer_product_id
            ORDER BY observed_at, try_cast(observation_id AS HUGEINT) NULLS LAST,
              observation_id)
        ), flagged AS (
          SELECT *, lag(timestamp_multiplicity) OVER (
            PARTITION BY retailer_id, store_id, retailer_product_id
            ORDER BY observed_at, try_cast(observation_id AS HUGEINT) NULLS LAST,
              observation_id) AS previous_timestamp_multiplicity
          FROM ordered
        )
        SELECT *, price - previous_price AS price_change,
          CASE WHEN previous_price > 0 THEN
            cast(price AS DOUBLE) / cast(previous_price AS DOUBLE) - 1 END AS price_return,
          coalesce(previous_price > 0 AND price > 0 AND price <> previous_price
            AND is_available AND previous_available
            AND currency = 'KZT' AND previous_currency = currency
            AND timestamp_multiplicity = 1 AND previous_timestamp_multiplicity = 1,
            false) AS clean_price_change,
          coalesce(canonical_product_id IS NOT NULL AND
            (match_method = 'manual' OR match_confidence >= 0.9), false)
            AS high_confidence_link
        FROM flagged
    """)


def build_panel(con, start: date, end: date) -> None:
    con.execute(f"""
        CREATE TABLE daily_panel AS
        WITH daily AS (
          SELECT * FROM events
          QUALIFY row_number() OVER (
            PARTITION BY retailer_id, store_id, retailer_product_id, cast(observed_at AS DATE)
            ORDER BY observed_at DESC, try_cast(observation_id AS HUGEINT) DESC NULLS LAST,
              observation_id DESC) = 1
        ), intervals AS (
          SELECT *, lead(cast(observed_at AS DATE), 1, DATE {literal(end)}) OVER (
            PARTITION BY retailer_id, store_id, retailer_product_id ORDER BY observed_at)
              AS next_event_date FROM daily
        )
        SELECT cast(d.day AS DATE) AS date, retailer_id, store_id, retailer_product_id,
          city_id, canonical_product_id, price, regular_price, is_promotion, is_available,
          currency, observed_at AS last_observed_at,
          date_diff('day', cast(observed_at AS DATE), d.day) AS state_age_days,
          cast(observed_at AS DATE) = d.day AS event_recorded_today,
          CASE WHEN cast(observed_at AS DATE) = d.day THEN 'event_recorded'
            ELSE 'carried_forward_unverified' END AS observation_status,
          NULL::BOOLEAN AS crawl_success_known,
          timestamp_multiplicity > 1 AS last_event_timestamp_ambiguous
        FROM intervals, LATERAL generate_series(
          greatest(cast(observed_at AS DATE), DATE {literal(start)}),
          least(next_event_date, DATE {literal(end)}) - INTERVAL 1 DAY,
          INTERVAL 1 DAY) d(day)
    """)


def run(export: Path, output: Path) -> None:
    import duckdb

    manifest_path = export / "manifest.json"
    verified = verify_manifest(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    # Refuse accidental overwrites of an earlier run.
    output.mkdir(parents=True, exist_ok=False)
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    con.execute("SET threads=4")
    con.execute("SET memory_limit='2GB'")
    con.execute(f"SET temp_directory={literal(output / 'spill')}")
    checks = []
    for entry, checked in zip(manifest["files"], verified):
        rows = con.execute("SELECT count(*) FROM read_parquet(?)", [str(checked.path)]).fetchone()[
            0
        ]
        if rows != entry["row_count"]:
            raise ValueError(f"Row count mismatch: {entry['path']}")
        checks.append({"path": entry["path"], "rows": rows, "bytes": checked.size_bytes})
    observation_files = [
        str(item.path)
        for item, entry in zip(verified, manifest["files"])
        if entry["path"].startswith("price_observations/")
    ]
    con.read_parquet(observation_files, hive_partitioning=False).create_view("input_observations")
    con.execute("CREATE TABLE observations AS SELECT * FROM input_observations")
    con.read_parquet(str(export / "product_links/frozen_product_link_mapping.parquet")).create_view(
        "links"
    )

    def query(sql):
        cursor = con.execute(sql)
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    totals = query("""SELECT count(*) AS observations,
        count(*) - count(DISTINCT observation_id) AS duplicate_ids,
        count(DISTINCT retailer_id) AS retailers,
        count(DISTINCT (retailer_id, store_id)) AS stores,
        count(DISTINCT (retailer_id, store_id, retailer_product_id)) AS offers,
        count(DISTINCT city_id) AS cities,
        min(observed_at) AS first_event, max(observed_at) AS last_event,
        count(*) FILTER (WHERE canonical_product_id IS NULL) AS unlinked,
        count(*) FILTER (WHERE price IS NULL OR price <= 0) AS invalid_prices,
        count(*) FILTER (WHERE quantity IS NULL OR unit IS NULL) AS missing_unit_metadata,
        count(*) FILTER (WHERE pack_count <= 0 OR quantity <= 0) AS invalid_pack_metadata,
        count(*) FILTER (WHERE is_promotion IS DISTINCT FROM (regular_price IS NOT NULL))
          AS promotion_flag_inconsistencies,
        count(*) FILTER (WHERE regular_price < price) AS reference_below_price,
        count(*) FILTER (WHERE link_record_created_at > observed_at) AS links_created_after_event,
        count(*) FILTER (WHERE observation_id IS NULL OR observed_at IS NULL
          OR retailer_id IS NULL OR store_id IS NULL OR retailer_product_id IS NULL
          OR city_id IS NULL OR currency IS NULL OR is_available IS NULL
          OR is_promotion IS NULL) AS missing_required_fields
        FROM observations""")[0]
    if totals["duplicate_ids"] or totals["missing_required_fields"]:
        raise ValueError(
            f"Resolve duplicate IDs or missing required fields before reconstruction: {totals}"
        )
    start = totals["first_event"].date().replace(day=1)
    last = totals["last_event"].date()
    end = date(last.year + (last.month == 12), last.month % 12 + 1, 1)
    if totals["observations"] != manifest["totals"]["price_observations"]:
        raise ValueError("Manifest observation total mismatch")
    build_events(con)
    build_panel(con, start, end)
    profiles = {}
    profiles["retailers"] = query("""SELECT retailer_id, count(*) AS events,
        count(DISTINCT store_id) AS stores, count(DISTINCT retailer_product_id) AS products,
        count(DISTINCT cast(observed_at AS DATE)) AS active_dates,
        min(cast(observed_at AS DATE)) AS first_date, max(cast(observed_at AS DATE)) AS last_date,
        count(*) FILTER (WHERE clean_price_change) AS clean_changes,
        count(*) FILTER (WHERE canonical_product_id IS NULL) AS unlinked
        FROM events GROUP BY retailer_id ORDER BY events DESC""")
    profiles["matching"] = query("""SELECT match_method, match_status, count(*) AS observations,
        min(match_confidence) AS min_confidence, median(match_confidence) AS median_confidence,
        max(match_confidence) AS max_confidence FROM events GROUP BY ALL ORDER BY observations DESC""")
    profiles["events"] = (
        query("""SELECT count(*) FILTER (WHERE previous_price IS NULL) AS initial_events,
        count(*) FILTER (WHERE clean_price_change) AS clean_changes,
        count(*) FILTER (WHERE clean_price_change AND high_confidence_link) AS high_confidence_changes,
        count(*) FILTER (WHERE clean_price_change AND previous_promotion = is_promotion)
          AS changes_without_promotion_transition,
        count(*) FILTER (WHERE timestamp_multiplicity > 1) AS tied_timestamp_rows,
        count(*) FILTER (WHERE previous_price = price) AS unchanged_price_events,
        median(date_diff('second', previous_observed_at, observed_at) / 3600.0) AS median_gap_hours,
        quantile_cont(date_diff('second', previous_observed_at, observed_at) / 3600.0, .95)
          AS p95_gap_hours,
        count(*) FILTER (WHERE clean_price_change AND abs(price_return) > 1) AS changes_over_100pct
        FROM events""")
    )
    profiles["panel"] = query("""SELECT count(*) AS rows,
        count(*) FILTER (WHERE event_recorded_today) AS event_days,
        count(*) FILTER (WHERE NOT event_recorded_today) AS carried_days,
        max(state_age_days) AS max_state_age_days FROM daily_panel""")
    profiles["mapping"] = query("""SELECT count(*) AS rows,
        count(*) FILTER (WHERE selected_for_observation_export) AS selected_rows,
        count(*) FILTER (WHERE barcode_overlap) AS barcode_overlap_rows,
        count(*) FILTER (WHERE valid_from IS NOT NULL OR valid_to IS NOT NULL) AS historical_validity_rows
        FROM links""")
    if profiles["mapping"][0]["rows"] != manifest["totals"]["product_link_mapping_rows"]:
        raise ValueError("Manifest mapping total mismatch")
    profiles["mapping_consistency"] = query("""SELECT count(*) AS unmatched_observation_links
        FROM observations o WHERE o.canonical_product_id IS NOT NULL AND NOT EXISTS (
          SELECT 1 FROM links l WHERE l.selected_for_observation_export
            AND l.retailer_id = o.retailer_id AND l.store_id = o.store_id
            AND l.retailer_product_id = o.retailer_product_id
            AND l.canonical_product_id = o.canonical_product_id)""")
    profiles["canonical_overlap"] = query("""WITH products AS (
        SELECT canonical_product_id, count(DISTINCT retailer_id) AS retailers,
          count(*) FILTER (WHERE clean_price_change AND high_confidence_link) AS changes,
          count(DISTINCT retailer_id) FILTER (WHERE clean_price_change AND high_confidence_link)
            AS changing_retailers,
          count(DISTINCT (unit, quantity, pack_count)) AS pack_variants
        FROM events WHERE canonical_product_id IS NOT NULL GROUP BY canonical_product_id)
        SELECT count(*) AS canonical_products, count(*) FILTER (WHERE retailers >= 2) AS multi_retailer,
          count(*) FILTER (WHERE changing_retailers >= 2) AS high_confidence_multi_retailer_changers,
          count(*) FILTER (WHERE pack_variants > 1) AS inconsistent_pack_products FROM products""")
    con.execute(
        """CREATE TABLE store_activity AS
        WITH stores AS (SELECT DISTINCT retailer_id, store_id FROM observations),
        dates AS (SELECT unnest(generate_series(?::DATE, ?::DATE - INTERVAL 1 DAY,
          INTERVAL 1 DAY))::DATE AS date),
        activity AS (SELECT retailer_id, store_id, cast(observed_at AS DATE) AS date,
          count(*) AS events FROM observations GROUP BY ALL)
        SELECT s.*, d.date, coalesce(a.events, 0) AS events,
          CASE WHEN a.events > 0 THEN 'some_events_recorded' ELSE 'unknown' END AS activity_status
        FROM stores s CROSS JOIN dates d LEFT JOIN activity a USING(retailer_id, store_id, date)
        """,
        [start, end],
    )
    # Each source change pairs with the first later same-direction target change in 72h.
    # This is descriptive, not a causal or out-of-sample diffusion estimate.
    con.execute("""CREATE TABLE lead_lag AS
        WITH eligible AS (SELECT * FROM events WHERE clean_price_change AND high_confidence_link),
        pairs AS (SELECT a.observation_id, a.retailer_id AS source_retailer,
          b.retailer_id AS target_retailer, min(date_diff('second', a.observed_at, b.observed_at))/3600.0
            AS lag_hours FROM eligible a JOIN eligible b
          ON a.canonical_product_id = b.canonical_product_id AND a.city_id = b.city_id
          AND a.retailer_id <> b.retailer_id AND sign(a.price_change) = sign(b.price_change)
          AND a.unit IS NOT DISTINCT FROM b.unit AND a.quantity IS NOT DISTINCT FROM b.quantity
          AND a.pack_count IS NOT DISTINCT FROM b.pack_count
          AND b.observed_at > a.observed_at
          AND b.observed_at <= a.observed_at + INTERVAL 72 HOURS
          GROUP BY a.observation_id, a.retailer_id, b.retailer_id)
        SELECT source_retailer, target_retailer, count(*) AS paired_source_changes,
          median(lag_hours) AS median_lag_hours FROM pairs GROUP BY ALL
        ORDER BY paired_source_changes DESC""")
    profiles["lead_lag"] = query("SELECT * FROM lead_lag")
    profiles["baseline"] = query("""SELECT retailer_id,
        count(*) FILTER (WHERE previous_price IS NOT NULL) AS observed_transitions,
        avg(cast(price = previous_price AS INT)) FILTER (WHERE previous_price IS NOT NULL)
          AS persistence_exact_accuracy,
        avg(abs(price - previous_price)) FILTER (WHERE previous_price IS NOT NULL)
          AS persistence_mae_kzt
        FROM events GROUP BY retailer_id ORDER BY retailer_id""")
    for table in ("events", "daily_panel", "store_activity"):
        con.execute(
            f"COPY {table} TO {literal(output / (table + '.parquet'))} (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    result = {
        "export_id": manifest["export_id"],
        "manifest_sha256": sha256_file(manifest_path),
        "duckdb_version": duckdb.__version__,
        "window": [str(start), str(end)],
        "verified_files": checks,
        "totals": totals,
        "profiles": profiles,
    }
    (output / "profile.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    lines = [
        "# August pilot quality report",
        "",
        f"Source: `{manifest['export_id']}`. Manifest SHA-256: `{result['manifest_sha256']}`.",
        "",
        f"Verified hashes, sizes and row counts for {len(checks)} Parquet files.",
        "",
        "## Main findings",
        "",
        (
            f"The pilot contains {totals['offers']:,} offers across {totals['stores']} stores "
            f"and {totals['cities']} cities. No duplicate observation IDs or missing required fields "
            f"were found. {totals['invalid_prices']:,} rows have nonpositive or missing prices; "
            f"{totals['reference_below_price']:,} have a reference price below the selling price."
        ),
        "",
        (
            f"The screen retains {profiles['events'][0]['clean_changes']:,} price changes, including "
            f"{profiles['events'][0]['high_confidence_changes']:,} with high-confidence links. "
            f"{profiles['canonical_overlap'][0]['high_confidence_multi_retailer_changers']:,} canonical "
            "products change at two or more retailers under that link screen."
        ),
        "",
        (
            f"{profiles['panel'][0]['carried_days'] / profiles['panel'][0]['rows']:.1%} of panel rows "
            f"carry an unverified earlier state. {totals['links_created_after_event']:,} observation "
            "rows use links created after the event; historical match availability cannot be assumed."
        ),
        "",
        (
            "The leading Small/Smallfood/Spar candidate pairs have median gaps of only minutes. "
            "Investigate shared source feeds, duplicated streams, and crawl scheduling before "
            "treating these as independent retailer reactions. Event counts also differ sharply "
            "across sources; several begin recording only late in August."
        ),
        "",
        "## Readiness and limitations",
        "",
        (
            "Descriptive analysis is available. Diffusion/hazard inference is deferred: the pilot has "
            "no crawl-coverage rows, no opening price snapshot, and only one month of events. "
            "Request store/day crawl coverage, a pre-August opening state, and additional months."
        ),
        "",
        (
            "The panel begins at each offer’s first event. Carried prices are last recorded states, "
            "not verified daily observations. Store activity proves only that some events occurred; "
            "silence does not prove an outage. All dates use UTC."
        ),
        "",
        (
            "Clean changes require positive old/new prices, available old/new states, KZT, and "
            "unambiguous consecutive timestamps. They include promotions and may span collection gaps. "
            "Initial events are excluded. High confidence means manual method or score ≥0.9; "
            "that threshold is exploratory and scores are not assumed calibrated."
        ),
        "",
        (
            "Mappings and pack attributes are frozen at export. Effective canonical barcode overlap "
            "can include the same source product, so it is not independent exact-match validation. "
            "Historical mapping validity is unavailable."
        ),
        "",
        (
            "Lead–lag pairs use the same canonical product, city, pack attributes, direction and a "
            "strictly later change within 72 hours. Missing pack attributes may match other missing "
            "attributes, so these are candidates for inspection. Targets can be reused across source "
            "changes. Counts lack a verified observation-risk denominator and do not establish influence."
        ),
        "",
        (
            "Persistence baseline predicts the previous recorded price at the next retained event. "
            "It is descriptive and event-conditioned, not an out-of-sample daily forecast. "
            "Model fitting and walk-forward comparison require broader history and observability."
        ),
        "",
    ]
    for title, rows in [("Totals", [totals])] + list(profiles.items()):
        lines += [f"## {title.replace('_', ' ')}", ""]
        if not rows:
            lines += ["No rows.", ""]
            continue
        columns = list(rows[0])
        if len(rows) == 1:
            lines += [f"- {key}: {value}" for key, value in rows[0].items()] + [""]
        else:
            lines += [
                "| " + " | ".join(columns) + " |",
                "| " + " | ".join(["---"] * len(columns)) + " |",
            ]
            lines += ["| " + " | ".join(str(row[c]) for c in columns) + " |" for row in rows]
            lines += [""]
    lines += [
        "## Reproduction",
        "",
        "`uv sync --group dev --group data`",
        "",
        (
            "`PYTHONPATH=src uv run python -m arzan_quant.pilot --export arzan-quant-20260913 "
            "--output data/private/pilot-profile-new`"
        ),
        "",
        "Output must be a new directory. Private row-level files must not be redistributed.",
    ]
    (output / "report.md").write_text("\n".join(lines) + "\n")
    con.close()
    print(f"Wrote pilot report and private datasets to {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.export, args.output)
