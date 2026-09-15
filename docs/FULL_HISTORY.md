# Full historical export — 14 September 2026

This is the archived 14 September run. Its observation assumption is superseded
by the [continuous-observation rerun](CONTINUOUS_HISTORY.md).

The delivered export contains 17,064,305 retained state-change observations from
12 October 2025 through 31 August 2026, covering 21 retailers, seven city IDs and
194 category IDs. It contains 657,632 frozen product-link mapping rows and zero
crawl-coverage rows. The manifest retains the label `pilot` and a 13 September
cutoff; the files cover completed months through August only. No September
observations are included, and the first month starts partway through October.

## Analysis design

The full-history configuration uses every delivered observation, with an exclusive
end of 1 September. It retains the usual 60-calendar-day initial training window,
30-day expanding-window test blocks, confidence threshold of 0.9, and three-day
lagged exposure window. No parameter is selected using held-out results.

The analysis explicitly uses September's frozen mappings retrospectively. There
are no historically dated link-validity records. Thus chronological model testing
is an evaluation on reconstructed historical metadata, not a real-time backtest.
A strict historically valid matching requirement would yield no matched model rows.

Successful store crawls are not assumed, and carried prices are not treated as
verified observations. Only eligible consecutive event-day states define outcomes.
This conditions the model on collection activity: the resulting event probabilities
are not market-wide daily price-change probabilities. Reported net changes may
cancel within-day movements. Shared collection feeds have not been verified, so
retailer connections are descriptive associations, not evidence of causality.

The export includes mixed retail categories, including non-food. The default
analysis covers that full sample; its index remains explicitly unclassified.
A verified grocery-category basket and reliable quote coverage are necessary
before calling the result a grocery inflation index. Official food-inflation target
and historical feature vintages were not supplied; that evaluation remains gated.

## Reproduction

From the project directory, with the research and development dependencies installed:

```sh
PYTHONPATH=src .venv/bin/python tools/audit_full_export.py \
  --export arzan-quant-20260913 \
  --output data/private/full-history-audit-new.json
PYTHONPATH=src .venv/bin/python -m arzan_quant.cli run-research \
  --export arzan-quant-20260913 \
  --settings configs/full-history-retrospective.json \
  --output data/private/full-history-new
```

Choose a new output directory for each run. The audit checks both manifest file
hashes and the supplementary checksum list, which includes the schema and
publication policy. The pipeline additionally validates actual Parquet row counts,
event conflicts, and required fields. Keep the raw export, reconstructed database
and row-level predictions private.

## Grocery-target sensitivity

`configs/full-history-grocery-scope.json` records 142 analyst-selected category IDs
covering 9,355,182 source observations. The selection uses the supplied Russian
category hierarchy: food, non-alcoholic drinks and infant food. It excludes alcohol,
tobacco, pet food, unclassified items and non-food goods. This is a transparent
research definition, not an official CPI mapping or historically verified taxonomy.

The companion analysis refits the same chronological models on eligible grocery
target rows. It retains the primary exposure variables, including context from
other retail categories. It therefore measures sensitivity to target composition,
not a wholly independent grocery-only network.

```sh
PYTHONPATH=src .venv/bin/python tools/evaluate_grocery_targets.py \
  --run data/private/full-history-final-20260914 \
  --scope configs/full-history-grocery-scope.json \
  --output data/private/full-history-grocery-new
PYTHONPATH=src .venv/bin/python tools/review_full_history.py \
  --run data/private/full-history-final-20260914 \
  --audit data/private/full-history-audit-20260914.json \
  --grocery data/private/full-history-grocery-new \
  --regimes data/private/full-history-event-regimes.json \
  --output data/private/full-history-review-new
```

## Local environment recovery

Some dependencies in the workspace's original environment were offloaded by macOS.
For this run, matching cached distribution versions were copied into a temporary
local environment at `/tmp/arzan-research-runtime`. The existing dependency lock
was unchanged. This temporary environment is replaceable: install the lockfile's
dependencies normally to reproduce the run. Package versions are recorded in each
run manifest. The initial waiting process was interrupted before ingestion; the
final run has its own directory and provenance.

The first full-data attempt completed 36,167,465 daily states but was stopped when
feature sorting approached the available disk limit. Its disposable query spill
files were removed; the reconstructed database was retained. Feature construction
was then changed to join prior-day evidence only for eligible outcomes. The resumed
run preserves the failed attempt in `attempt-1.json` and records the reused
checkpoint hash. It produces 1,990,575 primary matched modeling rows.

Direct comparison against the preceding feature implementation gave equivalent
model inputs (numeric tolerance 1e-12) for all four variants on an 80-day synthetic
export, including collection gaps. The test suite now has 34 passing tests,
including full-history lag equivalence and resumed-versus-fresh run equivalence.

Categorical model indicators use sparse matrices for full-history estimation. Dense
and sparse encodings match exactly on the regression fixture, including unseen
categories; fitted logistic/Poisson probabilities and conditional marks agree within
the tested numerical tolerances. The objective, penalty and chronological folds
are unchanged. The interrupted dense attempt is preserved in `attempt-2.json`.


## Event-composition audit

```sh
PYTHONPATH=src .venv/bin/python tools/audit_event_regimes.py \
  --export arzan-quant-20260913 \
  --output data/private/full-history-event-regimes.json
```

This audit compares each source offer's retained observations in timestamp order,
including the prior state across month boundaries. First records are not classified.
There are 15,438,970 availability-only transitions (90.48% of all retained rows),
versus 1,138,197 records with a price change relative to a known predecessor.
The share of price-changing records among rows with predecessors falls from about
99% in November–December to 2.64% in April. These are event-level diagnostics,
not the daily net-change outcomes used by the models. No records are relabeled
or removed using this post-hoc audit. Availability movements may be real or reflect
collection; the export does not identify their cause.
