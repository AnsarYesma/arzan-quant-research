"""Normalize immutable exports into a DuckDB connection without hiding data gaps.

Only market event fields participate in overlap conflict detection. Frozen catalogue
fields can differ across snapshots: the newest export wins, with its provenance kept.
"""

from __future__ import annotations

import json
from pathlib import Path

from .manifest import sha256_file, verify_manifest
from .schema import parse_timestamp
from .settings import ResearchSettings


def quote(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


OPTIONAL_COLUMNS = {
    "canonical_product_id": "VARCHAR",
    "category_id": "VARCHAR",
    "brand": "VARCHAR",
    "quantity": "DOUBLE",
    "unit": "VARCHAR",
    "pack_count": "INTEGER",
    "regular_price": "DOUBLE",
    "unit_price": "DOUBLE",
    "match_method": "VARCHAR",
    "match_confidence": "DOUBLE",
    "match_status": "VARCHAR",
    "barcodes": "VARCHAR[]",
    "link_record_created_at": "TIMESTAMPTZ",
    "link_valid_from": "TIMESTAMPTZ",
    "link_valid_to": "TIMESTAMPTZ",
}
REQUIRED_COLUMNS = {
    "observation_id",
    "observed_at",
    "retailer_id",
    "store_id",
    "city_id",
    "retailer_product_id",
    "price",
    "currency",
    "is_available",
    "is_promotion",
}
EVENT_CORE = (
    "retailer_id",
    "store_id",
    "retailer_product_id",
    "observed_at",
    "price",
    "regular_price",
    "currency",
    "is_available",
    "is_promotion",
)


def rows(con, sql: str) -> list[dict]:
    cursor = con.execute(sql)
    names = [c[0] for c in cursor.description]
    return [dict(zip(names, r)) for r in cursor.fetchall()]


def normalize(con, view: str, table: str, provenance: str, snapshot: str):
    columns = {r[0]: r[1] for r in con.execute(f"DESCRIBE {view}").fetchall()}
    if missing := REQUIRED_COLUMNS - columns.keys():
        raise ValueError(f"{provenance}: missing columns {sorted(missing)}")
    if columns["observed_at"] != "TIMESTAMP WITH TIME ZONE":
        raise ValueError("Parquet observed_at must be a timezone-aware timestamp")
    if any(columns[c] != "BOOLEAN" for c in ("is_available", "is_promotion")):
        raise ValueError("Parquet availability and promotion fields must be boolean")
    selected = [
        "cast(observation_id AS VARCHAR) AS observation_id",
        "cast(observed_at AS TIMESTAMPTZ) AS observed_at",
        *[
            f"cast({c} AS VARCHAR) AS {c}"
            for c in ("retailer_id", "store_id", "city_id", "retailer_product_id", "currency")
        ],
        "cast(price AS DOUBLE) AS price",
        "cast(is_available AS BOOLEAN) AS is_available",
        "cast(is_promotion AS BOOLEAN) AS is_promotion",
    ]
    selected += [
        f"cast({name if name in columns else 'NULL'} AS {kind}) AS {name}"
        for name, kind in OPTIONAL_COLUMNS.items()
    ]
    selected += [
        f"{quote(provenance)} AS export_id",
        f"{quote(snapshot)}::TIMESTAMPTZ AS snapshot_at",
    ]
    con.execute(f"CREATE TABLE {table} AS SELECT {', '.join(selected)} FROM {view}")


def load_exports(con, exports: list[Path], opening: Path | None = None) -> dict:
    """Accept complete or overlapping manifests. Missing crawl coverage stays unknown."""
    if not exports:
        raise ValueError("At least one export is required")
    con.execute("SET TimeZone='UTC'")
    sources, coverage_tables, provenance = [], [], []
    for i, root in enumerate(exports):
        manifest_path = root / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        if str(manifest.get("schema_version")) not in ("1", "1.0", "v1"):
            raise ValueError("Unsupported export schema version")
        files = verify_manifest(manifest_path)
        obs_files = []
        coverage_files = []
        counts = {
            "price_observations": 0,
            "product_link_mapping_rows": 0,
            "daily_crawl_coverage_rows": 0,
        }
        for entry, checked in zip(manifest["files"], files):
            n = con.execute("SELECT count(*) FROM read_parquet(?)", [str(checked.path)]).fetchone()[
                0
            ]
            if entry.get("row_count") != n:
                raise ValueError(f"Incorrect row count for {entry['path']}")
            if entry["path"].startswith("price_observations/"):
                obs_files.append(str(checked.path))
                counts["price_observations"] += n
            elif entry["path"].startswith("crawl_coverage/"):
                coverage_files.append(str(checked.path))
                counts["daily_crawl_coverage_rows"] += n
            elif entry["path"].startswith("product_links/"):
                counts["product_link_mapping_rows"] += n
        for key, value in counts.items():
            if key in manifest.get("totals", {}) and manifest["totals"][key] != value:
                raise ValueError(f"Manifest total mismatch: {key}")
        if not obs_files:
            raise ValueError("Export has no observation files")
        snapshot = parse_timestamp(
            manifest.get("mapping_snapshot_at", manifest["cutoff_exclusive"])
        ).isoformat()
        parse_timestamp(manifest["cutoff_exclusive"])
        con.read_parquet(obs_files, hive_partitioning=False, union_by_name=True).create_view(
            "_input"
        )
        table = f"_source_{i}"
        normalize(con, "_input", table, manifest["export_id"], snapshot)
        outside = con.execute(
            f"SELECT count(*) FROM {table} WHERE observed_at >= ?::TIMESTAMPTZ",
            [manifest["cutoff_exclusive"]],
        ).fetchone()[0]
        if outside:
            raise ValueError("Observation outside export cutoff")
        sources.append(table)
        if coverage_files:
            con.read_parquet(
                coverage_files, hive_partitioning=False, union_by_name=True
            ).create_view("_crawl")
            cols = {r[0] for r in con.execute("DESCRIBE _crawl").fetchall()}
            required = {"store_id", "date", "crawl_status", "is_complete_utc_day"}
            if required - cols:
                raise ValueError(f"Coverage missing {sorted(required - cols)}")
            # The agreed export may omit retailer_id. Only infer it for unambiguous stores.
            retailer = "c.retailer_id" if "retailer_id" in cols else "s.retailer_id"
            if "retailer_id" not in cols:
                ambiguous = con.execute(f"""SELECT count(*) FROM (
                    SELECT store_id FROM {table} GROUP BY store_id HAVING count(DISTINCT retailer_id)>1)
                    """).fetchone()[0]
                if ambiguous:
                    raise ValueError(
                        "Coverage needs retailer_id when store IDs are not globally unique"
                    )
            cov_table = f"_coverage_{i}"
            con.execute(f"""CREATE TABLE {cov_table} AS
                SELECT {retailer}::VARCHAR AS retailer_id, c.store_id::VARCHAR AS store_id,
                  c.date::DATE AS date, c.crawl_status::VARCHAR AS crawl_status,
                  c.is_complete_utc_day::BOOLEAN AS is_complete_utc_day,
                  {quote(snapshot)}::TIMESTAMPTZ AS snapshot_at
                FROM _crawl c LEFT JOIN (SELECT DISTINCT store_id, retailer_id FROM {table}) s
                  ON c.store_id = s.store_id
                  {"AND c.retailer_id = s.retailer_id" if "retailer_id" in cols else ""}
                """)
            coverage_tables.append(cov_table)
        provenance.append(
            {
                "export_id": manifest["export_id"],
                "status": manifest.get("status", "unspecified"),
                "manifest_sha256": sha256_file(manifest_path),
                "snapshot_at": snapshot,
                "counts": counts,
            }
        )
    if opening is not None:
        con.read_parquet(str(opening), hive_partitioning=False).create_view("_opening")
        normalize(
            con,
            "_opening",
            "_source_opening",
            "opening:" + sha256_file(opening),
            "1970-01-01T00:00:00+00:00",
        )
        sources.append("_source_opening")
        provenance.append({"opening_sha256": sha256_file(opening)})
    con.execute(
        "CREATE TABLE raw_events AS " + " UNION ALL ".join(f"SELECT * FROM {t}" for t in sources)
    )
    required_null = " OR ".join(f"{c} IS NULL" for c in REQUIRED_COLUMNS)
    if con.execute(f"SELECT count(*) FROM raw_events WHERE {required_null}").fetchone()[0]:
        raise ValueError("Null required event fields")
    bad_ids = " OR ".join(
        f"trim({c}) = ''"
        for c in (
            "observation_id",
            "retailer_id",
            "store_id",
            "city_id",
            "retailer_product_id",
            "currency",
        )
    )
    if con.execute(f"SELECT count(*) FROM raw_events WHERE {bad_ids}").fetchone()[0]:
        raise ValueError("Empty required event identifiers")
    core = ", ".join(EVENT_CORE)
    if con.execute(f"""SELECT count(*) FROM (SELECT observation_id FROM raw_events
        GROUP BY observation_id HAVING count(DISTINCT ({core})) > 1)""").fetchone()[0]:
        raise ValueError("Conflicting market event values for the same observation_id")
    # Also reject non-deterministic catalogue revisions at the same snapshot timestamp.
    meta = ", ".join(OPTIONAL_COLUMNS)
    if con.execute(f"""SELECT count(*) FROM (SELECT observation_id, snapshot_at FROM raw_events
        GROUP BY ALL HAVING count(DISTINCT ({meta}, city_id)) > 1)""").fetchone()[0]:
        raise ValueError("Conflicting metadata at the same snapshot timestamp")
    con.execute("""CREATE TABLE observations AS SELECT * FROM raw_events
        QUALIFY row_number() OVER (PARTITION BY observation_id ORDER BY snapshot_at DESC, export_id) = 1""")
    con.execute("DROP TABLE raw_events")
    if coverage_tables:
        con.execute(
            "CREATE TABLE raw_coverage AS "
            + " UNION ALL ".join(f"SELECT * FROM {t}" for t in coverage_tables)
        )
        if con.execute("""SELECT count(*) FROM raw_coverage WHERE retailer_id IS NULL OR store_id IS NULL
            OR date IS NULL OR crawl_status NOT IN ('successful','partial','failed','not_attempted')
            OR crawl_status IS NULL OR is_complete_utc_day IS NULL""").fetchone()[0]:
            raise ValueError("Invalid or unresolvable crawl coverage")
        if con.execute("""SELECT count(*) FROM (SELECT retailer_id, store_id, date, snapshot_at
            FROM raw_coverage GROUP BY ALL
            HAVING count(DISTINCT (crawl_status,is_complete_utc_day))>1)""").fetchone()[0]:
            raise ValueError("Conflicting crawl coverage at the same snapshot")
        con.execute("""CREATE TABLE coverage AS SELECT * FROM raw_coverage
            QUALIFY row_number() OVER (PARTITION BY retailer_id, store_id, date ORDER BY snapshot_at DESC)=1""")
        con.execute("DROP TABLE raw_coverage")
    else:
        con.execute("""CREATE TABLE coverage(retailer_id VARCHAR, store_id VARCHAR, date DATE,
            crawl_status VARCHAR, is_complete_utc_day BOOLEAN, snapshot_at TIMESTAMPTZ)""")
    for table in sources + coverage_tables:
        con.execute(f"DROP TABLE {table}")
    return {
        "sources": provenance,
        "observations": con.execute("SELECT count(*) FROM observations").fetchone()[0],
        "coverage_rows": con.execute("SELECT count(*) FROM coverage").fetchone()[0],
    }


def construct_panel(con, settings: ResearchSettings) -> dict:
    """Reconstruct state and daily risk eligibility. Failed crawls always censor rows."""
    cfg = settings
    if con.execute(
        """SELECT count(*) FROM observations WHERE export_id LIKE 'opening:%'
        AND observed_at>=?::DATE""",
        [cfg.start],
    ).fetchone()[0]:
        raise ValueError("Opening states must precede the requested start date")
    start, end = quote(cfg.start), quote(cfg.end)
    con.execute(f"""CREATE TABLE ordered_events AS
        SELECT *, count(*) OVER (PARTITION BY retailer_id, store_id, retailer_product_id, observed_at)
          AS timestamp_multiplicity FROM observations WHERE observed_at < {end}::DATE""")
    con.execute(f"""CREATE TABLE daily_states AS
        WITH last_daily AS (
          SELECT * FROM ordered_events QUALIFY row_number() OVER (
            PARTITION BY retailer_id, store_id, retailer_product_id, observed_at::DATE
            ORDER BY observed_at DESC, try_cast(observation_id AS HUGEINT) DESC NULLS LAST,
              observation_id DESC)=1
        ), intervals AS (
          SELECT *, lead(observed_at::DATE, 1, {end}::DATE) OVER (
            PARTITION BY retailer_id, store_id, retailer_product_id ORDER BY observed_at) AS next_date
          FROM last_daily
        )
        SELECT * EXCLUDE(next_date), d.day::DATE AS date,
          date_diff('day', observed_at::DATE, d.day) AS state_age_days,
          observed_at::DATE = d.day AS event_recorded_today
        FROM intervals, LATERAL generate_series(greatest(observed_at::DATE, {start}::DATE - INTERVAL 1 DAY),
            next_date - INTERVAL 1 DAY, INTERVAL 1 DAY) d(day)
        """)
    con.execute(f"""CREATE TABLE panel AS
        WITH evidence AS (
          SELECT p.* EXCLUDE(day), c.crawl_status, c.is_complete_utc_day,
            c.crawl_status = 'successful' AND c.is_complete_utc_day AS store_day_success,
            coalesce(c.crawl_status IN ('failed','partial','not_attempted')
              OR NOT c.is_complete_utc_day, false) AS known_collection_problem,
            coalesce(link_valid_from <= date AND (link_valid_to IS NULL OR link_valid_to > date),
              false) AS historical_link_valid,
            coalesce((match_method = 'manual' OR match_confidence >= {cfg.min_match_confidence})
              AND coalesce(match_status,'legacy_unspecified') NOT IN ('rejected','disabled','unmatched'),
              false) AS high_confidence_link
          FROM daily_states p LEFT JOIN coverage c USING(retailer_id, store_id, date)
        )
        SELECT *, coalesce(isfinite(price) AND price > 0 AND currency='KZT' AND is_available
            AND timestamp_multiplicity=1
            AND ({str(cfg.assume_continuous_observation).lower()}
                 OR state_age_days <= {cfg.max_state_age_days})
            AND NOT known_collection_problem
            AND (event_recorded_today OR {str(cfg.assume_continuous_observation).lower()} OR
              ({str(cfg.assume_store_success_confirms_state).lower()} AND store_day_success)), false)
            AS state_eligible,
          coalesce(canonical_product_id IS NOT NULL AND high_confidence_link
            AND (historical_link_valid OR {str(cfg.retrospective_mapping).lower()}), false)
            AS match_eligible,
          CASE WHEN known_collection_problem THEN 'collection_problem'
            WHEN event_recorded_today THEN 'event_evidence'
            WHEN {str(cfg.assume_continuous_observation).lower()} THEN 'assumed_continuous_observation'
            WHEN store_day_success THEN 'store_success_only'
            ELSE 'unknown' END AS evidence_type
        FROM evidence""")
    con.execute("DROP TABLE daily_states")
    # Adjacent verified states define daily outcomes. Unknown endpoints are never zero labels.
    con.execute(f"""CREATE TABLE transitions AS
        WITH lagged AS (
          SELECT *, lag(price) OVER w AS previous_price, lag(date) OVER w AS previous_date,
            lag(state_eligible) OVER w AS previous_state_eligible,
            lag(is_promotion) OVER w AS previous_promotion,
            lag(canonical_product_id) OVER w AS previous_canonical,
            lag(match_eligible) OVER w AS previous_match_eligible
          FROM panel WINDOW w AS (
            PARTITION BY retailer_id, store_id, retailer_product_id ORDER BY date)
        )
        SELECT *, coalesce(state_eligible AND previous_state_eligible
          AND previous_date = date - INTERVAL 1 DAY, false) AS outcome_eligible,
          CASE WHEN state_eligible AND previous_state_eligible
            AND previous_date = date - INTERVAL 1 DAY THEN ln(price/previous_price) END AS log_return,
          coalesce(is_promotion IS DISTINCT FROM previous_promotion, false) AS promotion_transition
        FROM lagged WHERE date >= {start}::DATE""")
    con.execute("DROP TABLE panel")
    con.execute("CREATE VIEW panel AS SELECT * FROM transitions")
    con.execute("DROP TABLE ordered_events")
    return rows(
        con,
        """SELECT count(*) AS panel_rows,
        count(*) FILTER(WHERE state_eligible) AS eligible_states,
        count(*) FILTER(WHERE outcome_eligible) AS eligible_transitions,
        count(*) FILTER(WHERE outcome_eligible AND abs(log_return)>1e-10) AS daily_changes,
        count(*) FILTER(WHERE match_eligible) AS matched_states,
        count(*) FILTER(WHERE known_collection_problem) AS collection_problem_rows,
        count(*) FILTER(WHERE evidence_type='unknown') AS unknown_rows
        FROM transitions""",
    )[0]
