# Running the research project

## Install and verify

From the project folder:

```bash
uv sync --group dev --group data --group research
uv run pytest
uv run ruff check src tests
```

The full optional runtime can also be installed from a wheel with the `research`
extra. Development commands below set `PYTHONPATH=src` explicitly because some
desktop environments mark editable-install `.pth` files hidden, causing Python to
skip them. Standard wheel installations do not require that development setting.

## Reproduce the synthetic research run

```bash
PYTHONPATH=src uv run python -m arzan_quant.cli generate-export \
  --output data/synthetic/demo --days 240
PYTHONPATH=src uv run python -m arzan_quant.cli run-research \
  --export data/synthetic/demo --settings data/synthetic/demo/settings.json \
  --output artifacts/demo
```

Use new output directories for each run. The generator records its known causal
mechanism in `truth.json`; `--independent` generates a no-propagation control.
Both include promotions and collection failures. View `report.md`, `dashboard.html`
and `diagnostics.png`. The dashboard works offline and embeds aggregate edges only.

To exercise the monthly inflation branch too, create a separate known-effect monthly
experiment with `generate-monthly-demo --output data/synthetic/monthly-demo`, then
pass its `monthly_features.parquet` and `target_vintages.parquet` files to the research
run using the two nowcast options below. That monthly simulation is independent of
the daily offer simulation and is not an official inflation series.

## August and new months

```bash
PYTHONPATH=src uv run python -m arzan_quant.cli run-research \
  --export arzan-quant-20260913 --settings configs/august-pilot.json \
  --output data/private/august-run
```

The August configuration deliberately preserves unknown crawl and mapping history;
it is expected to gate model estimation. The earlier `arzan_quant.pilot` profiler
remains useful for exploratory retrospective candidate pairs.

For multiple months, repeat `--export` for each verified export, extend `start`/`end`
in a copied settings JSON, and optionally pass `--opening opening.parquet`. The opening
file uses the observation schema and actual as-of timestamps preceding the window.
Do not relabel current catalogue prices as historical opening prices.

Exports may overlap. Exact event repeats are deduplicated, market-value conflicts
fail, and later frozen metadata snapshots replace earlier ones with provenance.
Crawl files under `crawl_coverage/` need `store_id`, `date`, `crawl_status`,
`is_complete_utc_day`, and preferably `retailer_id`. A missing retailer can be inferred
only when the store maps unambiguously in that export. Coverage without offer-level
evidence does not establish an inventory panel.

The run creates a disk-backed DuckDB database with a 2 GB memory budget and four
threads. The August compatibility run currently uses several GB of disk. Modeling
loads the eligible feature matrix in memory; assess memory and disk capacity before
running multi-year data. The application does not silently sample away observations.

## Incremental API workflow

Use the existing dedicated read-only API credential via environment variables.
`ingest-api` streams into a temporary gzip file and publishes the completed file
atomically. A failed fetch preserves any earlier destination. Duplicate IDs with
different payloads fail rather than silently disappearing.

```bash
PYTHONPATH=src uv run python -m arzan_quant.cli ingest-api \
  --observed-from 2026-09-01T00:00:00Z --observed-to 2026-09-02T00:00:00Z \
  --output data/private/september-01.jsonl.gz
PYTHONPATH=src uv run python -m arzan_quant.cli package-landing \
  --input data/private/september-01.jsonl.gz --output data/private/september-01-export \
  --observed-from 2026-09-01T00:00:00Z --observed-to 2026-09-02T00:00:00Z \
  --snapshot-at 2026-09-02T01:00:00Z
```

The timestamps above are illustrative. Use the actual requested window and catalogue
snapshot time. Add the resulting export to `run-research` with another `--export`.
API landing files do not invent coverage or historical link validity.

## Optional basket and nowcast inputs

`--weights weights.parquet` requires unique `(retailer_id, store_id,
retailer_product_id)` rows and a positive `weight` for each selected offer. Each
weighted offer needs an eligible opening price. Unmatched weights fail the run.

Pass `--monthly-features features.parquet --targets target-vintages.parquet` together
to exercise monthly inflation evaluation. See RESEARCH_METHODS.md for the exact
schemas and release policy. These files must represent genuine availability vintages
for real-time claims; historical reconstruction does not create them retroactively.

`build-monthly-vintage --run <completed-run> --forecast-at <UTC-timestamp> --output
<new-parquet>` extracts the latest complete month's index change and average peer
activity signal. It needs two consecutive sufficiently covered index months. It
stamps the export snapshot availability and refuses a forecast date before the
data was available. Save each new vintage; combine them for later monthly evaluation.
An optional `forecast_at` column specifies the actual forecast origin. When multiple
forecasts are supplied for one month, evaluation retains the earliest valid origin,
not a later forecast selected after inspecting the target.

## Failure and provenance

`run.json` records running/complete/failed status, source manifest hashes, settings,
code hashes, dependency versions and completed artifact hashes. A failed directory
is retained for diagnosis and never treated as a completed run. Choose a fresh output
for a retry. Raw data, database files and prediction rows remain private.

`tools/verify_dashboard.cjs` provides a browser smoke test and screenshot using
Playwright. It checks rendering and the retailer/threshold filters. Browser automation
requires Playwright and its Chromium runtime; core research execution does not.

## Full historical run and recovery

Use `configs/full-history-retrospective.json` for the delivered October 2025–August
2026 export. See `docs/FULL_HISTORY.md` for its assumptions, grocery-target
sensitivity and aggregate audit commands.

Feature construction now joins prior-day evidence to eligible outcomes before
building the modeling tables. It avoids copying and sorting all carried states;
it does not sample the export or turn unobserved days into no-change outcomes.
Synthetic equivalence checks cover the primary and all three robustness variants.

If a run fails after panel construction but before index/analytics tables are
created, repeat the original command with `--resume-panel`. Resume requires a
failed status, the same settings and optional inputs, unchanged panel-construction
code, matching input manifests, valid export hashes and an existing complete panel.
The previous attempt is archived inside the run directory, and the resumed
manifest records the checkpoint hash. Completed runs cannot be resumed. Use a
fresh output for changed windows, changed inputs, or changed panel rules.
