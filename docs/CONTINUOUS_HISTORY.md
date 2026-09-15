# Continuous-observation rerun

The owner confirmed continuous crawler coverage and accepted frozen historical
product mappings for this retrospective study. The corrected run retains unchanged
prices after quiet intervals, including intervals longer than seven days. Explicit
collection failures, unavailable offers, invalid prices and pre-entry dates remain
excluded. This changes the risk set; it does not invent price changes.

## Reproduction

From the project root, with research dependencies installed:

```sh
PYTHONPATH=src python -m arzan_quant.cli run-research \
  --export arzan-quant-20260913 \
  --settings configs/full-history-continuous.json \
  --output data/private/continuous-history-20260915

PYTHONPATH=src python tools/evaluate_grocery_targets.py \
  --run data/private/continuous-history-20260915 \
  --scope configs/full-history-grocery-scope.json \
  --output data/private/continuous-grocery-20260915

PYTHONPATH=src python tools/audit_continuous_predictions.py \
  --run data/private/continuous-history-20260915 \
  --output data/private/continuous-review-20260915

PYTHONPATH=src python tools/review_continuous_history.py \
  --run data/private/continuous-history-20260915 \
  --previous data/private/full-history-final-20260914 \
  --grocery data/private/continuous-grocery-20260915 \
  --output data/private/continuous-review-20260915
```

Output directories for model runs must be new. Raw inputs and predictions remain
private. The original study is preserved for comparison.

## What the comparison measures

Models use expanding training windows with at least 60 days before the first test
and successive 30-day holdouts. The baseline includes retailer, city, category,
weekday, lagged promotion state, lagged return and time since the last recorded
update. The diffusion specification additionally includes recent competitor,
cross-city and category activity. Thus its improvement is attributable to the
combined additional signals, not uniquely to competitors' actions. Exposures use
only earlier days, never the target day's prices. This design does not test
within-day propagation; weak daily forecasting results cannot rule that out.

The primary metrics are Brier error and log loss for the daily probability of a
net price change. Persistence and historical-frequency forecasts remain explicit
comparators. The marked-intensity model is a daily Poisson approximation; it is not
a continuous-time Hawkes fit. Directional coefficients are not causal estimates.

Barcode matching and excluding promotions provide alternate sample checks. The
recent-update sample intentionally recreates selection toward recently recorded
states and must not be interpreted as a necessary coverage filter under continuous
observation. Grocery-only targets retain the broad-retail exposure universe.

The optional paired score audit resamples seven-day blocks of daily aggregate
losses. It retains dependence between products on a given day and short temporal
dependence. Its interval is conditional on the fitted models and chosen design;
it does not account for research specification search or prove causality.

## Scaling and verification

The corrected sample is approximately ten times larger than the earlier sample.
The evaluator reads only required model inputs, stores identifiers as categorical
columns, uses sparse design matrices, and saves each model/test-window prediction
batch immediately. `predictions.parquet` is now a Parquet dataset directory; Pandas
can read it directly, while DuckDB can use `predictions.parquet/*.parquet`.

Aggregate metrics are observation-weighted fold metrics. RMSE is aggregated through
squared error before taking its square root. A parity test verifies that compact
categorical inputs and disk prediction batches reproduce the in-memory evaluation
and all saved predictions. There is no row subsampling or change to the likelihood,
regularization, features or train/test boundaries for scaling.

All 39 tests pass after these changes. The category context calculation now
preaggregates shared activity before joining individual targets. A direct temporal-join
comparison verifies exact equality, including NULL and differing categories. The running source snapshot is retained
privately in `data/private/continuous-history-code-20260915/attempt-2`; its hashes match the
run's recorded code provenance. Version 0.1.1 adds the final report layout and
preserves gaps in the index plot; these presentation changes do not alter the
recorded fits. Original run artifacts remain unchanged.

## Completed results

The primary sample contains 19,771,832 targets and 762,022 daily price changes.
Nine chronological holdouts cover 19,213,703 targets. Diffusion Brier error is
0.036167 versus baseline 0.036140 (+0.076%), with improvement in six windows.
Log loss improves slightly (0.153774 versus 0.153929). The scoring metrics are
mixed; the seven-day block-bootstrap interval for the paired Brier difference
spans zero.
Barcode matching gives +0.050%, excluding flagged promotions +0.095%, and the
11,398,621-observation grocery holdout gives +0.198%. The recently updated sample
contains 4,133,533 holdout observations and gives +1.755%; it deliberately changes
the risk set and is not a coverage gate under continuous observation.

The apparent April collapse was largely a selection artifact. With corrected
coverage, descriptive change rates are 3.89% after recent competitor activity
versus 3.85% otherwise. Directional agreement is 51.93%, compared with 50.07%
under an unadjusted independent-direction benchmark. These are weak aggregate
associations, not evidence of a causal response. The models do not test within-day
propagation.

The illustrative index still uses only 11 opening offers and publishes 179 of
324 days. No official inflation nowcast has been validated. The completed claim
is the daily price-diffusion study; index and nowcast limitations remain explicit.

See `data/private/continuous-review-20260915/report.md` for the integrated findings
and `artifacts/packages-continuous-history/` for corrected version 0.1.1 packages.

