"""Paired daily score audit with seven-day circular-block bootstrap uncertainty."""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

import duckdb
import numpy as np


def audit(run: Path, output: Path, include_association=True):
    con = duckdb.connect()
    con.execute("SET memory_limit='1GB'")
    con.execute("SET threads=2")
    scores = con.execute(
        """WITH daily AS (
          SELECT date, model, count(*) n,
            sum(pow(greatest(1e-9,least(1-1e-9,probability))-changed,2)) sse
          FROM read_parquet(?) WHERE model IN
            ('hazard_baseline','hazard_diffusion','boosted_baseline','boosted_competitor')
          GROUP BY date,model)
          SELECT date,model,n,sse FROM daily ORDER BY date,model""",
        [str(run / "predictions.parquet" / "*.parquet")],
    ).df()
    rng = np.random.default_rng(20260913)
    length = 7

    def compare(baseline, candidate):
        left = scores[scores.model == baseline][["date", "n", "sse"]]
        right = scores[scores.model == candidate][["date", "n", "sse"]]
        paired = left.merge(right, on=["date", "n"], suffixes=("_baseline", "_candidate"))
        n = len(paired)
        if not n:
            return {
                "status": "models_not_present",
                "baseline": baseline,
                "candidate": candidate,
                "days": 0,
                "observations": 0,
            }
        estimates = []
        values = paired[["n", "sse_baseline", "sse_candidate"]].to_numpy()
        for _ in range(5000):
            starts = rng.integers(0, n, size=(n + length - 1) // length)
            selected = ((starts[:, None] + np.arange(length)) % n).ravel()[:n]
            total = values[selected].sum(axis=0)
            estimates.append((total[2] - total[1]) / total[0])
        return {
            "status": "evaluated",
            "baseline": baseline,
            "candidate": candidate,
            "days": n,
            "observations": int(paired.n.sum()),
            "candidate_minus_baseline_brier": float(
                (paired.sse_candidate.sum() - paired.sse_baseline.sum()) / paired.n.sum()
            ),
            "block_bootstrap_95_percent_interval": np.quantile(
                estimates, [0.025, 0.975]
            ).tolist(),
        }

    comparisons = {
        "logistic_competitor_information": compare("hazard_baseline", "hazard_diffusion"),
        "boosted_competitor_information": compare("boosted_baseline", "boosted_competitor"),
    }
    logistic = comparisons["logistic_competitor_information"]
    association = []
    if include_association:
        db = duckdb.connect(str(run / "research.duckdb"), read_only=True)
        cursor = db.execute("""SELECT peer_active_days>0 AS recently_exposed,
            count(*) AS observations, sum(changed) AS changes, avg(changed) AS change_rate,
            count(*) FILTER(WHERE changed=1 AND abs(peer_mark)>1e-10) AS directional_changes,
            avg(cast(sign(magnitude)=sign(peer_mark) AS INTEGER))
              FILTER(WHERE changed=1 AND abs(peer_mark)>1e-10) AS same_direction_fraction
            , avg(cast(magnitude>0 AS INTEGER))
          FILTER(WHERE changed=1 AND abs(peer_mark)>1e-10) AS target_increase_fraction
        , avg(cast(peer_mark>0 AS INTEGER))
          FILTER(WHERE changed=1 AND abs(peer_mark)>1e-10) AS peer_increase_fraction
        FROM features GROUP BY 1 ORDER BY 1""")
        association = [
            dict(zip([col[0] for col in cursor.description], row)) for row in cursor.fetchall()
        ]
        for row in association:
            target, peer = row["target_increase_fraction"], row["peer_increase_fraction"]
            row["independent_direction_agreement"] = (
                target * peer + (1 - target) * (1 - peer) if target is not None else None
            )
        db.close()
    result = {
        "script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "descriptive_peer_association": association,
        "association_interpretation": "Unadjusted comparisons of eligible target days with versus without same-city competitor activity in the previous three days. Direction compares the target return to the average recent peer return, conditional on a target change and a nonzero peer mean. Neither comparison identifies a causal response.",
        "days": logistic["days"],
        "observations": logistic["observations"],
        "diffusion_minus_baseline_brier": logistic["candidate_minus_baseline_brier"],
        "block_bootstrap_95_percent_interval": logistic[
            "block_bootstrap_95_percent_interval"
        ],
        "comparisons": comparisons,
        "method": "Paired daily summed losses, seven-day circular blocks, 5000 replicates, seed 20260913; preserves within-day dependence. Descriptive uncertainty conditional on fitted models; not a causal test or allowance for model selection.",
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "paired_score_audit.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n"
    )
    scores.to_json(output / "daily_scores.json", orient="records", date_format="iso", indent=2)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scores-only", action="store_true")
    args = parser.parse_args()
    audit(args.run, args.output, include_association=not args.scores_only)
