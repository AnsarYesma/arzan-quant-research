# Arzan Price-Diffusion Research

Research code for measuring how grocery price shocks propagate between retailers,
cities, categories, and competing products in Kazakhstan.

The repository is designed around the Arzan research API and the versioned Parquet
contract described in `docs/data_contract.md`. Raw production data is private and
must never be committed. Public tests and examples use deterministic synthetic data.

## Observation-assumption correction — 15 September 2026

The owner clarified that crawler coverage should be assumed continuous. The earlier
study excluded quiet days, creating a major sampling distortion: March's selected
price-change rate falls from 99.98% to 4.20% when those days are included. The earlier
forecast scores are not a final answer under this assumption. The code now supports
continuous observation. The corrected primary evaluation is complete on 19,213,703
held-out observations: diffusion Brier error is 0.036167 versus 0.036140 for the
baseline (about 0.08% worse), with improvement in 6 of 9 windows. Log loss improves
slightly, so the scoring metrics are mixed. A seven-day
block-bootstrap interval spans improvement and deterioration. Robustness and
grocery-only reruns are complete: barcode matching gives +0.05% Brier error,
excluding flagged promotions +0.09%, and grocery targets +0.20%. These comparisons
do not establish a reliable incremental daily forecasting advantage.

- [Published aggregate results](docs/RESULTS.md)
- [Rerun design and reproduction](docs/CONTINUOUS_HISTORY.md)
- Corrected version 0.1.1 distributions: `artifacts/packages-continuous-history/`.

## Post-study model extensions — 15 September 2026

Version 0.2.0 implements the study's recommended follow-up: point-in-time competitor
price gaps, cheapest status, own repricing history, 1/3/7/14-day exposure windows,
paired logistic and depth-two boosted-tree comparisons, response-timing and
time-to-next-change diagnostics, a timestamp audit, and a focused coarse-grained
excitation experiment. The full corrected-history rerun is complete.

Competitor features improve pooled logistic Brier error by 0.273%, but the paired
block-bootstrap interval includes zero. They worsen boosted-tree Brier error by
0.635%, with the interval entirely on the worse side. Cross-retailer excitation also
worsens the focused subset's pooled Brier and log loss. These exploratory extensions
do not validate price contagion.

- [Published aggregate results](docs/RESULTS.md)
- [Methods and interpretation](docs/RESEARCH_METHODS.md)


See [the quantified audit and correction](docs/OBSERVATION_ASSUMPTION_AUDIT.md).

## Archived study — 14 September 2026 (superseded observation assumption)

The delivered October 2025–August 2026 export has now been analyzed: 17,064,305
records, 36,167,465 reconstructed daily states and 1,990,575 matched model targets.
The nine-window retrospective evaluation finds no pooled forecasting improvement
from diffusion signals; the baseline and diffusion models both perform worse than
a no-change forecast. An event audit identifies a major change in availability-event
composition. This is a negative empirical result, not a validated forecasting service.

- [Superseded full-history design](docs/FULL_HISTORY.md)
- [Methods, data limitations and reproduction](docs/FULL_HISTORY.md)

The findings include barcode/promotion/recent-state checks and an analyst-defined
grocery-target sensitivity. Raw data and predictions remain private. The limited
opening basket, missing crawl evidence and absent feature/target vintages prevent
validation of a real-time grocery index or official food-inflation forecast.

## Research workflow

The project now includes verified multi-export loading, overlap/conflict handling,
opening-state reconstruction, crawl-aware daily eligibility, lagged retailer/city/
category features, daily hazard and marked-intensity models, conditional magnitude
models, chronological evaluation, matching/promotion/observation robustness checks,
a sample price index, release-aware inflation evaluation and an offline network
dashboard. Synthetic exports exercise both a known follower and an independent control.

Production estimation is gated when eligible history or historical mappings are
missing. Successful synthetic execution is not evidence of production forecast accuracy.
The full completion checklist and remaining audit are in `docs/BUILD_PLAN.md`.

## License

The repository's software and included documentation are available under the
[MIT License](LICENSE). This license does not apply to the excluded Arzan.kz
production data or product mappings; see [the publication boundary](PUBLICATION.md).

See `docs/OPERATIONS.md` for reproducible commands and input contracts, and
`docs/RESEARCH_METHODS.md` for model definitions and limitations.

## Quick start

```bash
uv sync --group dev --group data --group research
uv run pytest
PYTHONPATH=src uv run python -m arzan_quant.cli generate-export --output data/synthetic/demo --days 240
PYTHONPATH=src uv run python -m arzan_quant.cli run-research --export data/synthetic/demo --settings data/synthetic/demo/settings.json --output artifacts/demo
```

To use the research API, point the process at the separately supplied credential:

```bash
set -a
source /secure/path/.env.arzan-quant-research
set +a

uv run arzan-quant ingest-api \
  --observed-from 2026-08-01T00:00:00+00:00 \
  --observed-to 2026-08-02T00:00:00+00:00 \
  --output data/private/2026-08-01.jsonl.gz
```

Do not copy the production credential into this repository.

## Research sequence

The pilot profiler verifies file hashes, sizes and row counts, then writes a quality
report, screened events, daily last-recorded states and store activity under a private
output directory. Install the data dependencies first:

```bash
uv sync --group dev --group data
PYTHONPATH=src uv run python -m arzan_quant.pilot --export arzan-quant-20260913 --output data/private/pilot-profile-new
```

Use a new output directory for each run. Carried states are explicitly unverified;
event activity cannot substitute for crawl coverage. Lead–lag summaries and the
persistence baseline are descriptive, not causal or out-of-sample estimates.

1. Validate the August pilot, manifest, schema, coverage, and frozen mapping.
2. Construct clean price-change events and retailer/store/day observability flags.
3. Establish non-diffusion baselines and descriptive lead-lag statistics.
4. Fit survival/hazard and marked point-process models.
5. Run walk-forward, exact-match, high-confidence-link, and outage-filtered robustness tests.
6. Add an exploratory inflation nowcast only when enough monthly target history exists.
