"""Compare event-only selection with owner-assumed continuous observation.

Read-only audit of the original completed daily-state database; no model refit.
Run from the project root.
"""

import json
from pathlib import Path

import duckdb

c = duckdb.connect("data/private/full-history-final-20260914/research.duckdb", read_only=True)
c.execute(
    "SET threads=4; SET memory_limit='2GB'; SET TimeZone='UTC'; SET temp_directory='/tmp/arzan-assumption-spill'"
)
q = """WITH eligible AS (
SELECT retailer_id,store_id,retailer_product_id,date,price,previous_price,previous_date,
outcome_eligible,log_return,match_eligible,previous_match_eligible,canonical_product_id,previous_canonical,
coalesce(isfinite(price) AND price>0 AND currency='KZT' AND is_available
AND timestamp_multiplicity=1 AND NOT known_collection_problem,false) AS new_state_eligible
FROM transitions), lagged AS (
SELECT *,lag(new_state_eligible) OVER(PARTITION BY retailer_id,store_id,retailer_product_id ORDER BY date) AS prev_new
FROM eligible), compared AS (
SELECT *,coalesce(new_state_eligible AND prev_new AND previous_date=date-INTERVAL 1 DAY,false) AS new_outcome,
coalesce(match_eligible AND previous_match_eligible AND canonical_product_id=previous_canonical,false) AS matching
FROM lagged)
SELECT strftime(date,'%Y-%m') AS month,count(*) AS states,
count(*) FILTER(WHERE outcome_eligible AND matching) AS original_matched_transitions,
count(*) FILTER(WHERE outcome_eligible AND matching AND abs(log_return)>1e-10) AS original_changes,
count(*) FILTER(WHERE new_outcome AND matching) AS continuous_matched_transitions,
count(*) FILTER(WHERE new_outcome AND matching AND abs(CASE WHEN price>0 AND previous_price>0 THEN ln(price/previous_price) END)>1e-10) AS continuous_changes
FROM compared GROUP BY 1 ORDER BY 1"""
cur = c.execute(q)
names = [x[0] for x in cur.description]
r = [dict(zip(names, v)) for v in cur.fetchall()]
Path("data/private/observation-assumption-audit/monthly_comparison.json").write_text(
    json.dumps(r, indent=2) + "\n"
)
for x in r:
    print(
        x["month"],
        x["original_matched_transitions"],
        round(100 * x["original_changes"] / max(1, x["original_matched_transitions"]), 2),
        x["continuous_matched_transitions"],
        round(100 * x["continuous_changes"] / max(1, x["continuous_matched_transitions"]), 2),
        flush=True,
    )
