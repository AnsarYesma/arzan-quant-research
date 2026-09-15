"""Summarize the continuous-observation rerun without presupposing the result."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from arzan_quant.manifest import sha256_file


def review(run, previous, output, grocery=None):
    output.mkdir(parents=True, exist_ok=True)
    result = json.loads((run / "results.json").read_text())
    provenance = json.loads((run / "run.json").read_text())
    assert provenance["status"] == "complete"
    assert provenance["settings"]["assume_continuous_observation"] is True
    for name, digest in provenance["artifacts"].items():
        assert sha256_file(run / name) == digest, name
    import duckdb

    from arzan_quant.reporting import create_figure, create_report
    from arzan_quant.warehouse import rows

    con = duckdb.connect(str(run / "research.duckdb"), read_only=True)
    index_rows = rows(con, "SELECT date,index_value,weight_coverage FROM price_index ORDER BY date")
    monthly = con.execute(
        "SELECT strftime(date,'%Y-%m') AS month_name, count(*) n, avg(changed) rate FROM features GROUP BY 1 ORDER BY 1"
    ).df()
    con.close()
    old_con = duckdb.connect(str(previous / "research.duckdb"), read_only=True)
    old_monthly = old_con.execute(
        "SELECT strftime(date,'%Y-%m') AS month_name, count(*) n, avg(changed) rate FROM features GROUP BY 1 ORDER BY 1"
    ).df()
    old_con.close()
    result["assume_continuous_observation"] = True
    create_figure(output, result, index_rows)
    create_report(output, result, index_rows)
    old = json.loads((previous / "results.json").read_text())
    aggregate = result["evaluation"]["aggregate"]
    delta = 100 * (
        aggregate["hazard_diffusion"]["brier"] / aggregate["hazard_baseline"]["brier"] - 1
    )
    folds = [f for f in result["evaluation"]["folds"] if f["status"] == "evaluated"]
    log_delta = 100 * (
        aggregate["hazard_diffusion"]["log_loss"] / aggregate["hazard_baseline"]["log_loss"] - 1
    )
    wins = sum(
        f["metrics"]["hazard_diffusion"]["brier"] < f["metrics"]["hazard_baseline"]["brier"]
        for f in folds
    )
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(13, 5), constrained_layout=True)
    axes[0].plot(
        old_monthly.month_name, 100 * old_monthly.rate, marker="o", label="Earlier selected sample"
    )
    axes[0].plot(monthly.month_name, 100 * monthly.rate, marker="o", label="Continuous observation")
    axes[0].set_title("The sampling correction removes the apparent April break")
    axes[0].set_ylabel("Daily price-change rate (%)")
    axes[0].tick_params(axis="x", rotation=60)
    axes[0].legend(frameon=False)
    differences = [
        100
        * (f["metrics"]["hazard_diffusion"]["brier"] / f["metrics"]["hazard_baseline"]["brier"] - 1)
        for f in folds
    ]
    axes[1].bar(
        [f["train_end_exclusive"] for f in folds],
        differences,
        color=["#b05244" if d > 0 else "#2b7a78" for d in differences],
    )
    axes[1].axhline(0, color="black", linewidth=0.7)
    axes[1].set_title("Diffusion forecast error relative to baseline")
    axes[1].set_ylabel("Brier error change (%) — negative is better")
    axes[1].tick_params(axis="x", rotation=60)
    fig.savefig(output / "correction-and-forecast.png", dpi=160)
    plt.close(fig)
    lines = [
        "# Arzan: corrected full-history study",
        "",
        f"Adding recent competitor, cross-city and category activity {'reduces' if delta < 0 else 'increases'} held-out Brier error by {abs(delta):.3f}% relative to the baseline. It improves {wins} of {len(folds)} chronological test windows.",
        "",
        "This measures incremental predictive information at a daily horizon using activity from the preceding three days. It does not establish that one retailer caused another to change prices, and it does not test propagation within the same day.",
        "",
        "## Corrected observation assumption",
        "",
        "The crawler is assumed to observe continuously. An unchanged carried price remains observed after seven quiet days. Unavailable offers, invalid prices, explicit collection failures and observations before product entry remain excluded. Frozen product mappings are accepted for this retrospective study.",
        "",
        f"Eligible model targets: {old['features']['rows']:,} before correction; {result['features']['rows']:,} after correction. The original forecast results are superseded for this observation assumption.",
        "",
        "## Held-out performance",
        "",
        "| Model | Test observations | Brier error | Log loss | Predicted change rate | Actual change rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, m in aggregate.items():
        lines.append(
            f"| {name} | {m['n']:,} | {m['brier']:.6f} | {m['log_loss']:.6f} | {m['mean_predicted_probability']:.2%} | {m['event_rate']:.2%} |"
        )
    lines += [
        "",
        "Lower Brier error and log loss are better. Persistence predicts no change; training_rate predicts the historical training frequency. The matched baseline/diffusion comparison uses logistic models for both. Marked intensity also changes the model family, so its score alone does not isolate the contribution of diffusion signals.",
        "",
        f"Log loss changes by {log_delta:+.3f}% versus baseline. The scoring metrics therefore give a mixed picture; the reported block-bootstrap interval concerns Brier error.",
        "",
        "## Stability",
        "",
        "| Sample | Held-out observations | Diffusion Brier error change versus baseline |",
        "| --- | ---: | ---: |",
        f"| Primary | {aggregate['hazard_baseline']['n']:,} | {delta:+.3f}% |",
    ]
    comparisons = dict(result["robustness"])
    if grocery:
        gp = json.loads((grocery / "run.json").read_text())
        assert gp["status"] == "complete"
        for name, digest in gp["artifacts"].items():
            assert sha256_file(grocery / name) == digest, name
        assert gp["parent_run_sha256"] == sha256_file(run / "run.json")
        comparisons["grocery_targets"] = {
            "evaluation": json.loads((grocery / "results.json").read_text())
        }
    for name, variant in comparisons.items():
        a = variant["evaluation"]["aggregate"]
        if a:
            d = 100 * (a["hazard_diffusion"]["brier"] / a["hazard_baseline"]["brier"] - 1)
            lines.append(f"| {name} | {a['hazard_baseline']['n']:,} | {d:+.3f}% |")
    flag_path = output / "promotion_flag_audit.json"
    if flag_path.exists():
        flag = json.loads(flag_path.read_text())
        lines += [
            "",
            f"The export contains {flag['flagged_promotion_records']:,} promotion-flagged records out of {flag['records']:,} ({flag['flagged_promotion_records'] / flag['records']:.2%}). This sensitivity uses the supplied flags; its held-out sample size shows how much the filter changes the analysis.",
        ]
    lines += [
        "",
        "The recent_state_only check deliberately selects recently updated records; it is a sample-selection sensitivity, not a coverage requirement. The no-promotions sample excludes current and prior promotion states and is a retrospective sensitivity.",
        "",
        "## Verification",
        "",
        "The tests recover an injected lagged follower pattern and check an independent control. They also verify quiet-day eligibility, past-only features, unchanged earlier fits after adding future data, sparse/dense model parity, and streamed/in-memory prediction parity. These checks support implementation correctness; they do not guarantee that the chosen model captures every real-world mechanism.",
        "",
        "## Interpretation and CV use",
        "",
        "A negative result is useful if it survives a valid design. The strongest CV claim is building and auditing a large longitudinal panel, finding an eligibility defect, and testing incremental predictive value with chronological holdouts. Do not claim causal price contagion, a trading strategy, or validated inflation forecasting from these results.",
        "",
        f"Price index: {result['index']['basket_offers']:,} opening-basket offers; {result['index']['published_days']} published days. {result['index']['limitation']}",
        "",
        f"Inflation nowcast: {result['nowcast']['status']}. This component has no validated forecasting result without suitable target and feature vintages.",
        "",
        f"[Interactive diagnostics]({output.resolve() / 'dashboard.html'})",
        "",
        f"[Complete aggregate results]({run.resolve() / 'results.json'})",
    ]
    lines += [
        "",
        f"![Sampling correction and forecast comparison]({output.resolve() / 'correction-and-forecast.png'})",
    ]
    paired_path = output / "paired_score_audit.json"
    if paired_path.exists():
        paired = json.loads(paired_path.read_text())
        lines += [
            "",
            "## Descriptive peer association",
            "",
            "| Recent peer activity | Observations | Price-change rate | Same-direction share among directional changes |",
            "| --- | ---: | ---: | ---: |",
        ]
        for row in paired["descriptive_peer_association"]:
            same = row["same_direction_fraction"]
            same_text = f"{same:.2%}" if same is not None else "—"
            lines.append(
                f"| {'Yes' if row['recently_exposed'] else 'No'} | {row['observations']:,} | {row['change_rate']:.2%} | {same_text} |"
            )
        lines += ["", paired["association_interpretation"]]
        for row in paired["descriptive_peer_association"]:
            expected = row.get("independent_direction_agreement")
            if row["recently_exposed"] and expected is not None:
                lines += [
                    "",
                    f"Given the observed mix of increases and decreases, independent target and peer directions would agree {expected:.2%} of the time. This is an unadjusted marginal benchmark, not a causal counterfactual.",
                ]
        low, high = paired["block_bootstrap_95_percent_interval"]
        lines += [
            "",
            f"Paired Brier difference (diffusion minus baseline): {paired['diffusion_minus_baseline_brier']:+.6f}; seven-day block-bootstrap 95% interval [{low:+.6f}, {high:+.6f}]. This is conditional uncertainty for the chosen fitted models, not a causal confidence interval.",
        ]
    (output / "report.md").write_text("\n".join(lines) + "\n")
    (output / "evidence.json").write_text(
        json.dumps(
            {
                "run_sha256": sha256_file(run / "run.json"),
                "script_sha256": sha256_file(Path(__file__)),
                "renderer_sha256": sha256_file(Path(create_report.__code__.co_filename)),
                "paired_audit_sha256": sha256_file(paired_path) if paired_path.exists() else None,
                "brier_change_percent": delta,
                "fold_wins": wins,
                "folds": len(folds),
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("run", "previous", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--grocery", type=Path)
    args = parser.parse_args()
    review(args.run, args.previous, args.output, args.grocery)
