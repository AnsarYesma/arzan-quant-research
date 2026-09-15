"""Summarize a completed historical run using aggregate, auditable evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from arzan_quant.manifest import sha256_file


def make_figure(output, coverage, result, grocery_result=None):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    fig, axes = plt.subplots(2, 2, figsize=(13, 9), constrained_layout=True)
    fig.suptitle("Arzan historical price research · retrospective event-day sample", fontsize=17)
    months = coverage["months"]
    axes[0, 0].bar(
        [m["month"] for m in months], [m["observations"] for m in months], color="#2b7a78"
    )
    if "event_regime_months" in coverage:
        axes[0, 0].plot(
            [m["month"] for m in months],
            [coverage["event_regime_months"][m["month"]]["changed_price_rows"] for m in months],
            color="#b05244",
            marker="o",
            label="Price-changing records",
        )
        axes[0, 0].legend(frameon=False)
    axes[0, 0].tick_params(axis="x", rotation=55)
    axes[0, 0].set_yscale("log")
    axes[0, 0].set_title("Retained observations vs price-changing records")
    axes[0, 0].set_ylabel("Recorded observations (log scale)")
    folds = [f for f in result["evaluation"]["folds"] if f["status"] == "evaluated"]
    differences = [
        100
        * (f["metrics"]["hazard_diffusion"]["brier"] / f["metrics"]["hazard_baseline"]["brier"] - 1)
        for f in folds
    ]
    axes[0, 1].bar(
        [f["train_end_exclusive"] for f in folds],
        differences,
        color=["#b05244" if d > 0 else "#2b7a78" for d in differences],
    )
    axes[0, 1].axhline(0, color="#24343d", linewidth=0.8)
    axes[0, 1].tick_params(axis="x", rotation=55)
    axes[0, 1].set_title("Does diffusion improve the baseline?")
    axes[0, 1].set_ylabel("Brier error change (%) · negative is better")
    aggregate = result["evaluation"]["aggregate"]
    names = [
        n
        for n in ("training_rate", "hazard_baseline", "hazard_diffusion", "marked_intensity")
        if n in aggregate
    ]
    positions = np.arange(len(names))
    axes[1, 0].bar(
        positions - 0.18,
        [100 * aggregate[n]["mean_predicted_probability"] for n in names],
        width=0.36,
        label="Predicted",
        color="#2b7a78",
    )
    axes[1, 0].bar(
        positions + 0.18,
        [100 * aggregate[n]["event_rate"] for n in names],
        width=0.36,
        label="Observed",
        color="#dbac58",
    )
    axes[1, 0].set_xticks(positions, [n.replace("_", " ") for n in names], rotation=20)
    axes[1, 0].set_title("Average predicted vs observed change probability")
    axes[1, 0].set_ylabel("Percent of selected held-out transitions")
    axes[1, 0].legend(frameon=False)
    variants = {"Primary": result["evaluation"]} | {
        k.replace("_", " "): v["evaluation"] for k, v in result["robustness"].items()
    }
    if grocery_result is not None:
        variants["Grocery targets"] = grocery_result
    values = {
        name: 100
        * (
            v["aggregate"]["hazard_diffusion"]["brier"] / v["aggregate"]["hazard_baseline"]["brier"]
            - 1
        )
        for name, v in variants.items()
        if v["aggregate"]
    }
    axes[1, 1].barh(
        list(values),
        list(values.values()),
        color=["#b05244" if d > 0 else "#2b7a78" for d in values.values()],
    )
    axes[1, 1].axvline(0, color="#24343d", linewidth=0.8)
    axes[1, 1].set_title("Sensitivity to matching and promotions")
    axes[1, 1].set_xlabel("Brier error change (%) · negative is better")
    for ax in axes.flat:
        ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(output / "research-summary.png", dpi=160)
    plt.close(fig)


def review(
    run: Path, audit: Path, output: Path, grocery: Path | None = None, regimes: Path | None = None
):
    result = json.loads((run / "results.json").read_text())
    provenance = json.loads((run / "run.json").read_text())
    coverage = json.loads(audit.read_text())
    if provenance["status"] != "complete":
        raise ValueError("Research run is not complete")
    for name, digest in provenance["artifacts"].items():
        if sha256_file(run / name) != digest:
            raise ValueError(f"Artifact checksum mismatch: {name}")
    grocery_result = None
    if grocery is not None:
        grocery_provenance = json.loads((grocery / "run.json").read_text())
        if grocery_provenance["status"] != "complete":
            raise ValueError("Grocery run is not complete")
        if grocery_provenance["parent_run_sha256"] != sha256_file(run / "run.json"):
            raise ValueError("Grocery run uses a different parent run")
        for name, digest in grocery_provenance["artifacts"].items():
            if sha256_file(grocery / name) != digest:
                raise ValueError(f"Grocery artifact checksum mismatch: {name}")
        grocery_result = json.loads((grocery / "results.json").read_text())
    regime_result = None
    if regimes is not None:
        from collections import Counter, defaultdict

        regime_result = json.loads(regimes.read_text())
        if regime_result["manifest_sha256"] != coverage["manifest_sha256"]:
            raise ValueError("Event-regime audit uses a different export")
        monthly = defaultdict(Counter)
        for item in regime_result["monthly_retailer_summary"]:
            for key, value in item.items():
                if isinstance(value, int):
                    monthly[item["month"]][key] += value
        coverage["event_regime_months"] = monthly
    scope = coverage["scope"][0]
    metrics = result["evaluation"]["aggregate"]
    baseline = metrics.get("hazard_baseline", {})
    diffusion = metrics.get("hazard_diffusion", {})
    folds = [f for f in result["evaluation"]["folds"] if f["status"] == "evaluated"]
    output.mkdir(parents=True, exist_ok=False)
    output.chmod(0o700)
    lines = [
        "# Arzan full-history research findings",
        "",
        "Completed-data analysis · 14 September 2026",
        "",
        (
            f"The analysis uses **{scope['observations']:,} observations** across "
            f"**{scope['retailers']} retailers** and **{scope['cities']} city IDs**, "
            "from 12 October 2025 through 31 August 2026. All supplied observations were ingested; "
            "the eligible modeling sample is determined by the documented evidence and matching rules."
        ),
        "",
    ]
    if baseline:
        improvement = 100 * (baseline["brier"] - diffusion["brier"]) / baseline["brier"]
        wins = sum(
            f["metrics"]["hazard_diffusion"]["brier"] < f["metrics"]["hazard_baseline"]["brier"]
            for f in folds
        )
        lines += [
            (
                f"Adding diffusion signals changes Brier error by **{-improvement:+.2f}%** relative "
                f"to the baseline hazard across **{diffusion['n']:,} held-out rows**. "
                f"Diffusion has lower Brier error in **{wins} of {len(folds)} evaluated windows**. "
                "These are retrospective predictive comparisons on selected event-day transitions, "
                "not a causal or real-time validation."
            ),
            "",
        ]
    if baseline and diffusion["brier"] > metrics["persistence"]["brier"]:
        lines += [
            (
                "The diffusion model also has higher Brier error than a simple no-change forecast. "
                "The primary run does not establish useful forecast performance. Differences across "
                "test windows must be considered when interpreting the pooled score."
            ),
            "",
        ]
    lines += [
        "## What was delivered",
        "",
        "- Verified full-export ingestion and reconstructed daily states.",
        "- Expanding-window baseline, diffusion-hazard and daily marked-intensity models.",
        "- Barcode-exposure, no-promotion and recent-state sensitivity runs.",
        "- Retailer association network, promotion follow-up and index-coverage diagnostics.",
        "- Saved model fits, private predictions, aggregate report, interactive dashboard and provenance.",
        "",
        "## Data coverage and restrictions",
        "",
        (
            f"The export has {coverage['verified_parquet_files']} verified Parquet files and "
            f"{coverage['verified_checksum_entries']} checked supplementary checksum entries. "
            f"There are {scope['unlinked_rows']:,} observations without canonical links and "
            f"{scope['invalid_price_rows']:,} invalid price rows. "
            "No crawl coverage or historical link-validity timestamps were supplied. "
            "The manifest cutoff is 13 September, but delivered observations end on 31 August."
        ),
        "",
        "| Month | Observations | Retailers | Cities |",
        "| --- | ---: | ---: | ---: |",
    ]
    lines += [
        f"| {m['month']} | {m['observations']:,} | {m['retailers']} | {m['cities']} |"
        for m in coverage["months"]
    ]
    lines += [
        "",
        (
            "Retailer coverage expands sharply during the sample, and the first month is partial. "
            "The data cover less than the originally requested 12 months. The sample includes non-food "
            "retail; no verified grocery-only classification is asserted."
        ),
        "",
        "## Eligible sample",
        "",
        "| Measure | Count |",
        "| --- | ---: |",
    ]
    lines += [f"| {key.replace('_', ' ')} | {value:,} |" for key, value in result["panel"].items()]
    lines += [
        f"| Matched model rows | {result['features']['rows']:,} |",
        "",
        (
            "Unknown carried states do not become no-change labels. Outcomes require eligible adjacent "
            "daily endpoints. Frozen September mappings are used retrospectively. A requirement for "
            "historically valid mappings would leave zero matched observations. Probabilities therefore "
            "describe the selected recorded-activity sample, not all products on all days."
        ),
        "",
        "## Held-out prediction",
        "",
        "| Model | Held-out rows | Brier ↓ | Log loss ↓ | Return MAE ↓ |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, m in metrics.items():
        lines.append(
            f"| {name} | {m['n']:,} | {m['brier']:.6f} | {m['log_loss']:.6f} | {m['return_mae']:.6f} |"
        )
    if diffusion:
        lines += [
            "",
            (
                f"The diffusion model's mean predicted probability is "
                f"{100 * diffusion['mean_predicted_probability']:.2f}%, compared with "
                f"{100 * diffusion['event_rate']:.2f}% observed. Its return MAE is "
                f"{diffusion['return_mae']:.6f}, versus {metrics['persistence']['return_mae']:.6f} "
                "for a zero-return forecast. Return metrics use log-price changes."
            ),
            "",
        ]
    lines += [
        "### Results by test window",
        "",
        "| Test start | Test end (exclusive) | Training rows | Test rows | Baseline Brier | Diffusion Brier | Error change |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for f in result["evaluation"]["folds"]:
        if f["status"] != "evaluated":
            lines.append(
                f"| {f['train_end_exclusive']} | {f['test_end_exclusive']} | {f['train_rows']:,} | {f['test_rows']:,} | Not estimated | Not estimated | Insufficient data |"
            )
            continue
        a = f["metrics"]["hazard_baseline"]["brier"]
        b = f["metrics"]["hazard_diffusion"]["brier"]
        lines.append(
            f"| {f['train_end_exclusive']} | {f['test_end_exclusive']} | {f['train_rows']:,} | {f['test_rows']:,} | {a:.6f} | {b:.6f} | {100 * (b - a) / a:+.2f}% |"
        )
    lines += [
        "",
        (
            "The initial training period is 60 calendar days; subsequent test blocks are 30 days "
            "(the last may be shorter). Fitting and preprocessing use earlier rows only. Chronological "
            "splitting does not remove look-ahead from frozen catalogue metadata. Scores are point "
            "estimates; no significance claim or confidence interval is implied."
        ),
        "",
        "## Robustness",
        "",
        "| Variant | Held-out rows | Baseline Brier | Diffusion Brier | Error change |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, v in result["robustness"].items():
        a = v["evaluation"]["aggregate"]
        if not a:
            lines.append(f"| {name} | 0 | Not estimated | Not estimated | — |")
            continue
        base = a["hazard_baseline"]["brier"]
        diff = a["hazard_diffusion"]["brier"]
        lines.append(
            f"| {name} | {a['hazard_diffusion']['n']:,} | {base:.6f} | {diff:.6f} | {100 * (diff - base) / base:+.2f}% |"
        )
    lines += [
        "",
        (
            "The barcode variant restricts peer exposures using independently supplied source barcodes. "
            "The no-promotion variant changes both training and evaluation samples. Recent-state filtering "
            "may be identical to the primary run because eligible endpoints already require event-day evidence. "
            "These variants are sensitivity checks, not independent replications."
        ),
        "",
        "## Retailer associations and propagation timing",
        "",
        "| Source → target | Exposed rows | Exposed change rate | Target overall rate | Mean exposure lag (days) |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for e in result["network"][:15]:
        lines.append(
            f"| {e['source_retailer']} → {e['target_retailer']} | {e['exposed_risk_rows']:,} | {100 * e['exposed_change_rate']:.2f}% | {100 * e['baseline_rate']:.2f}% | {e['mean_exposure_lag_days']:.2f} |"
        )
    lines += [
        "",
        (
            "These are the 15 most-supported connections, ordered by exposed-row count. The lag "
            "summarizes source activity within a fixed three-day window; it is not an estimated transmission "
            "delay or half-life. Unexposed controls, common shocks, shared feeds, collection timing and "
            "sample composition can explain associations. No retailer is established as a causal leader."
        ),
        "",
        "## Promotions, index and inflation",
        "",
    ]
    total = sum(p["changes"] for p in result["promotions"])
    complete = sum(p["complete_followups"] for p in result["promotions"])
    lines += [
        (
            f"Of {total:,} eligible net daily changes, {complete:,} have seven fully eligible subsequent days. "
            "Incomplete follow-up is censored, rather than counted as price persistence. "
            "Detailed promotion-state breakdowns are saved in the run results."
        ),
        "",
        (
            f"The {result['index']['label']} has {result['index']['basket_offers']:,} opening offers "
            f"and {result['index']['published_days']} days meeting the 80% observed-weight threshold. "
            "It is not an expenditure-weighted CPI series. No missing index values are filled to manufacture "
            "monthly coverage."
        ),
        "",
        (
            f"Inflation evaluation status: **{result['nowcast']['status']}**. "
            "Official target vintages, historically available feature vintages, adequate monthly history, "
            "verified grocery classifications and reliable quote coverage are still needed. The delivered "
            "change-event history alone cannot establish a real-time grocery index or food-inflation forecast."
        ),
        "",
        "## Reproduction and evidence",
        "",
        f"- Completed run: `{run.resolve()}`.",
        f"- Full-export audit: `{audit.resolve()}`.",
        "- Configuration: `configs/full-history-retrospective.json`.",
        "- Methods and reproduction: `docs/FULL_HISTORY.md` and `docs/RESEARCH_METHODS.md`.",
        "- The run manifest records dependency versions, source hashes, input hashes and artifact hashes.",
        "- Raw exports, database files and row-level predictions remain private; only aggregate findings may be shared.",
        "",
    ]
    if regime_result is not None:
        total = sum(coverage["event_regime_months"].values(), Counter())
        section = [
            "## A major change in event composition",
            "",
            (
                f"**{100 * total['availability_only_rows'] / total['rows']:.2f}% of all retained observations** "
                "change only availability, with the same price, reference price and currency as the "
                "preceding record for that offer. First observations are not assigned an event type. "
                "The supplied data should therefore not be described as 17 million price changes."
            ),
            "",
            "| UTC month | Records with predecessor | Price-changing share | Availability-only share |",
            "| --- | ---: | ---: | ---: |",
        ]
        for month, counts in sorted(coverage["event_regime_months"].items()):
            n = counts["with_predecessor"]
            section.append(
                f"| {month} | {n:,} | {100 * counts['changed_price_rows'] / n:.2f}% | {100 * counts['availability_only_rows'] / n:.2f}% |"
            )
        section += [
            "",
            (
                "Percentages in this table use records with a predecessor as their denominator. "
                "The April shift coincides with a major prediction failure: the April 10–May 10 "
                "held-out sample has a 3.42% price-change rate, while the diffusion model predicts "
                "96.85% on average. This is evidence of a large change in the selected sample, "
                "not proof of its cause. Retained crawl logs and source-change history are needed "
                "to distinguish real availability dynamics from collection effects. No rows were "
                "removed or relabeled using this post-hoc diagnostic."
            ),
            "",
        ]
        position = lines.index("## Held-out prediction")
        lines[position:position] = section
    if grocery_result is not None:
        grocery_metrics = grocery_result["aggregate"]
        section = [
            "## Food and non-alcoholic grocery targets",
            "",
            (
                "This sensitivity refits the same models on an analyst-defined set of 142 food "
                "category IDs, including infant food and excluding alcohol, pet food, unknown "
                "categories and non-food items. Category assignments are the frozen September "
                "snapshot. Exposures retain the broader retail context; this is not a separate "
                "grocery-only network or an official CPI basket."
            ),
            "",
            "| Model | Held-out rows | Brier | Log loss | Return MAE |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        for name, m in grocery_metrics.items():
            section.append(
                f"| {name} | {m['n']:,} | {m['brier']:.6f} | {m['log_loss']:.6f} | {m['return_mae']:.6f} |"
            )
        if grocery_metrics:
            a = grocery_metrics["hazard_baseline"]["brier"]
            b = grocery_metrics["hazard_diffusion"]["brier"]
            section += [
                "",
                (
                    f"Diffusion changes grocery-target Brier error by **{100 * (b / a - 1):+.2f}%** "
                    "relative to its refitted baseline. This remains a retrospective, "
                    "collection-selected comparison."
                ),
                "",
            ]
        position = lines.index("## Retailer associations and propagation timing")
        lines[position:position] = section
    make_figure(output, coverage, result, grocery_result)
    lines.insert(
        4, "![Coverage, rolling evaluation, calibration and sensitivity](research-summary.png)\n"
    )
    (output / "report.md").write_text("\n".join(lines))
    dashboard = (run / "dashboard.html").read_text()
    dashboard = dashboard.replace('src="diagnostics.png"', 'src="research-summary.png"')
    dashboard = dashboard.replace(
        "<h2>Index and diagnostics</h2>", "<h2>Coverage and model diagnostics</h2>"
    )
    dashboard = dashboard.replace(
        "Index values use an opening basket and a minimum observed weight threshold. This is not official CPI.",
        f"The exploratory index has only {result['index']['basket_offers']} opening offers and "
        f"{result['index']['published_days']} eligible days out of {result['index']['days']}. "
        "It cannot support a continuous grocery inflation series. Official inflation evaluation remains gated.",
    )
    dashboard = dashboard.replace(
        '<p id="readiness"></p>',
        "<p><strong>Retrospective event-day study.</strong> Frozen September mappings and changing "
        "availability-event coverage limit interpretation. The diffusion model does not beat the "
        'no-change benchmark in the primary pooled evaluation.</p><p id="readiness"></p>',
    )
    dashboard = dashboard.replace('max="500" value="20"', 'max="500" value="500"')
    (output / "dashboard.html").write_text(dashboard)
    evidence = {
        "run_manifest_sha256": sha256_file(run / "run.json"),
        "audit_sha256": sha256_file(audit),
        "report_sha256": sha256_file(output / "report.md"),
        "figure_sha256": sha256_file(output / "research-summary.png"),
        "dashboard_sha256": sha256_file(output / "dashboard.html"),
        "review_script_sha256": sha256_file(Path(__file__)),
        "verified_run_artifacts": list(provenance["artifacts"]),
    }
    if regimes is not None:
        evidence["event_regime_audit_sha256"] = sha256_file(regimes)
    if grocery is not None:
        evidence["grocery_run_sha256"] = sha256_file(grocery / "run.json")
    (output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(output / "report.md")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--grocery", type=Path)
    parser.add_argument("--regimes", type=Path)
    args = parser.parse_args()
    review(args.run, args.audit, args.output, args.grocery, args.regimes)
