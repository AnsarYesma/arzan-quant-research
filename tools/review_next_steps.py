"""Create the private integrated review for the post-study modeling extensions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from arzan_quant.experiments import response_timing
from arzan_quant.reporting import dump_json


def percent(candidate, baseline):
    return 100 * (candidate / baseline - 1)


def review(run: Path, audit_path: Path, output: Path):
    result = json.loads((run / "results.json").read_text())
    audit = json.loads(audit_path.read_text())
    with duckdb.connect(str(run / "research.duckdb"), read_only=True) as con:
        timing = response_timing(con)
    output.mkdir(parents=True, exist_ok=True)
    dump_json(output / "response_timing.json", timing)

    overall = timing["overall"]
    isolated = timing["isolated_events"]
    survival = timing["time_to_next_change"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), constrained_layout=True)
    axes[0].axhline(0, color="#566", lw=1)
    axes[0].plot(
        [row["lag_days"] for row in overall],
        [100 * row["adjusted_rate_difference"] for row in overall],
        marker="o",
        label="All linked target-days",
    )
    axes[0].plot(
        [row["lag_days"] for row in isolated],
        [100 * row["adjusted_rate_difference"] for row in isolated],
        marker="s",
        label="Isolated source event",
    )
    axes[0].set(title="Calendar-group-adjusted response profile", xlabel="Lag (days)", ylabel="Percentage-point difference")
    axes[0].legend()
    for direction, label in ((-1, "Peer price cut"), (1, "Peer price increase")):
        selected = [row for row in survival if row["source_direction"] == direction]
        axes[1].plot(
            [row["horizon"] for row in selected],
            [100 * row["cumulative_change_probability"] for row in selected],
            marker="o",
            label=label,
        )
    axes[1].set(title="Time to next target price change", xlabel="Horizon (days)", ylabel="Cumulative probability (%)")
    axes[1].legend()
    fig.savefig(output / "response-timing.png", dpi=160)
    plt.close(fig)

    scores = result["evaluation"]["aggregate"]
    excitation = result["excitation_experiment"]["aggregate"]
    comparisons = audit["comparisons"]
    logistic = comparisons["logistic_competitor_information"]
    tree = comparisons["boosted_competitor_information"]
    lines = [
        "# Arzan next-steps model review",
        "",
        "Status: complete. Primary metric: chronological held-out Brier error.",
        "",
        "## Main model comparison",
        "",
        "| Family | Baseline Brier | With competitor features | Relative change | Better windows |",
        "| --- | ---: | ---: | ---: | ---: |",
        f"| Logistic | {scores['hazard_baseline']['brier']:.6f} | {scores['hazard_diffusion']['brier']:.6f} | {percent(scores['hazard_diffusion']['brier'], scores['hazard_baseline']['brier']):+.3f}% | 6/9 |",
        f"| Boosted tree | {scores['boosted_baseline']['brier']:.6f} | {scores['boosted_competitor']['brier']:.6f} | {percent(scores['boosted_competitor']['brier'], scores['boosted_baseline']['brier']):+.3f}% | 4/9 |",
        "",
        f"The logistic candidate-minus-baseline Brier difference is {logistic['candidate_minus_baseline_brier']:+.6f}; its seven-day block-bootstrap 95% interval is [{logistic['block_bootstrap_95_percent_interval'][0]:+.6f}, {logistic['block_bootstrap_95_percent_interval'][1]:+.6f}], which includes zero.",
        "",
        f"The boosted-tree difference is {tree['candidate_minus_baseline_brier']:+.6f}; its interval is [{tree['block_bootstrap_95_percent_interval'][0]:+.6f}, {tree['block_bootstrap_95_percent_interval'][1]:+.6f}], entirely on the worse side for competitor features.",
        "",
        "The best pooled Brier score is the boosted baseline without competitor features. The logistic competitor model improves pooled Brier and log loss, but its primary-metric uncertainty interval crosses zero. Metrics remain exploratory because all historical windows had already been inspected.",
        "",
        "## Focused excitation experiment",
        "",
        f"The 100-product subset contains {result['excitation_experiment']['selection']['risk_days']:,} risk-days and {result['excitation_experiment']['selection']['changes']:,} changes. Cross-retailer excitation changes Brier by {percent(excitation['cross_retailer_excitation']['brier'], excitation['time_varying_baseline']['brier']):+.3f}% and log loss by {percent(excitation['cross_retailer_excitation']['log_loss'], excitation['time_varying_baseline']['log_loss']):+.3f}% versus the time-varying baseline; it improves Brier in 3 of 9 windows. This does not support an overall predictive gain.",
        "",
        "The raw timestamps have substantial within-day variation, but they are collection timestamps and do not prove exact price-change times. The fitted experiment therefore remains coarse-grained daily Poisson excitation, not continuous-time Hawkes.",
        "",
        "## Response timing",
        "",
        "The adjusted lag profile is mixed rather than monotone. Isolated events show their largest positive differences at days 14 (+0.414 percentage points) and 7 (+0.249 points), suggesting calendar cadence is a plausible alternative explanation. These plots are descriptive associations, not causal event-study estimates.",
        "",
        "![Response timing and time to next change](response-timing.png)",
        "",
        "## Conclusion",
        "",
        "Improved own-history features and nonlinear modeling reduce overall error relative to the earlier baseline, but the evidence for incremental competitor information remains unstable and model-dependent. The defensible conclusion remains negative: do not claim validated price contagion.",
    ]
    (output / "report.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    review(args.run, args.audit, args.output)
