# Research methods and interpretation

## Unit of analysis and missingness

An offer is `(retailer_id, store_id, retailer_product_id)`. The daily panel is the
latest recorded state at the end of each UTC day, initialized only from an actual
earlier event or an opening-state Parquet file. Prices before the first state are
unknown. A same-timestamp tie is ordered deterministically by numeric event ID and
flagged ambiguous; ambiguous states are ineligible.

Missing/nonpositive/nonfinite prices, unavailable offers, unsupported currency,
old states and known collection problems are excluded from analytical risk rows.
Invalid states interrupt a carry-forward chain: the prior valid price is not carried
across a subsequent invalid or unavailable state. No-event days remain uncertain.

By default only a same-day event is direct evidence. Setting
`assume_store_success_confirms_state=true` additionally treats a successful, complete
store-day crawl as evidence that an unchanged offer remained observed. This is an
explicit coverage assumption, not a fact provided by a store-level counter. Partial,
failed, not-attempted and incomplete-day logs censor rows even when other events exist.

A daily outcome requires adjacent eligible states. Zero labels cannot be inferred
across an unknown endpoint. Daily net changes can hide intraday reversals. This
limits the daily model's interpretation relative to the raw event stream.

## Mapping and duplicate exports

Overlapping exports are deduplicated by observation ID. Conflicting market values
fail the run. Frozen catalogue revisions select the latest snapshot, independently
of export argument ordering. Same-snapshot metadata conflicts also fail.

By default cross-product features require explicit historical link validity on the
relevant days. Link creation timestamps alone do not prove historical validity.
`retrospective_mapping=true` enables a clearly retrospective analysis of frozen links.
Neither policy reconstructs missing histories of pack/category/brand metadata.
Production point-in-time claims require suitable metadata vintages as well as event
and link validity. The current August export has no link validity intervals.

High-confidence matching uses manual method or a configured confidence threshold.
The barcode robustness variant additionally requires intersection between the two
source offers' barcode lists and equal, nonmissing positive pack attributes. It does
not use the canonical effective barcode union as independent match evidence.
Scores are not assumed to be calibrated probabilities.

Retailers assigned to the same `feed_groups` family cannot expose each other in the
cross-retailer features. Assign groups only from evidence about source dependence.
Multiple source stores changing the same product on the same day contribute one
source-retailer activity day, with their marks averaged.

## Forecast origin and predictors

Each row predicts a target day's net price change using only earlier days. Baseline
features include the prior offer state, promotion flag, lagged return, recorded-state
age, days since the offer's last actual price change, 7/30/90-day offer repricing
rates, retailer/city/category and weekday controls. Competitor features add prior-day
matched-peer price gaps, whether the offer was cheapest, the number of priced peer
families, same-product other-retailer activity over 1/3/7/14 days, its signed mark and
exponential decay, same-product other-city activity within a retailer, and same-city
other-product activity within and outside the category. Pack metadata must match for
direct cross-retailer, price-gap and same-product cross-city features.

The default exponential kernel is `exp(-lag_days)` truncated to `exposure_days`.
It is fixed rather than fitted; use sensitivity analyses before interpreting timing.
Category activity is a broad competing-product proxy, not proof of substitution.

## Models and validation

- Persistence forecasts no change and zero return.
- The training-rate benchmark forecasts a smoothed historical event rate.
- The baseline daily hazard is a penalized logistic GLM of own-state and calendar/
  retailer/city/category controls.
- The competitor daily hazard adds the lagged competitor price/activity features.
- Fixed depth-two histogram-gradient-boosted trees are fit both with and without
  competitor features. Training is deterministically capped; all held-out rows are
  scored. Smoothed categorical encodings use training data only.
- The marked intensity model is a penalized Poisson GLM using those features. The
  probability of at least one daily event is `1-exp(-intensity)`. This is a binned
  point-process approximation, not continuous-time multivariate Hawkes estimation.
- Conditional signed log-return marks use ridge regression among training changes;
  probability times conditional mark gives the unconditional expected return.

All scaling, category encodings and coefficients are fitted using the expanding training
window alone. Chronological test blocks never train their own models. Row counts,
event counts, optimizer convergence, Brier score, log loss, return MAE/RMSE and
calibration bins are saved. Models and their encoders are saved for every evaluated
fold. Sparse-history folds are explicitly skipped. No random train/test split is used.

Three robustness analyses repeat evaluation with source-barcode matching, exclusion
of promotion states/transitions, and only recently recorded states. These can change
the target sample; a lower score alone does not establish a stronger model.
The primary comparison metric is fixed as Brier error; log loss and calibration are
secondary. Within each logistic or boosted-tree family, the baseline and competitor
versions use identical folds and risk rows. Hyperparameters are fixed before scoring.
Because all existing historical windows have been inspected, these extensions remain
exploratory even with chronological validation.

The response-timing diagnostic reports lags through 14 days, direction, retailer and
category heterogeneity. It includes a retailer-category-date mean adjustment and an
isolated-event view excluding target-days linked to multiple source events. These are
descriptive controls, not causal identification.

The focused excitation experiment selects frequently repriced products observed at
multiple retailers and compares daily Poisson intensity models with and without
cross-retailer excitation on the same folds and risk set. A timestamp-resolution audit
is saved alongside it. This is explicitly a coarse-grained daily experiment, not a
continuous-time Hawkes likelihood.

Penalized coefficients are predictive associations. No significance, causal
identification or official inflation accuracy is claimed by successful execution.

## Promotion persistence

The diagnostic checks whether a price change retains its direction relative to its
pre-change price after seven days. It requires every follow-up day to be eligible.
The end of a data window and collection gaps censor follow-up. These future outcomes
are used only for description, never fed into forecast features.

## Index and inflation target vintages

The index uses a fixed opening basket and geometric price relatives. Default weights
give equal weight to each canonical product and equal weight to its source offers;
unlinked offers are distinct products. Alternatively supply positive offer weights.
It renormalizes available basket weight each day and suppresses values below the
configured coverage threshold. Coverage, eligible quotes and promotion weight remain
visible. Composition effects remain possible. This is not expenditure-weighted CPI.

Configure verified grocery category IDs before calling the basket a grocery index.
Without them the output is explicitly an unclassified sample price index.

Monthly inflation evaluation accepts supplied feature vintages (`month`, `available_at`,
`index_change`, `diffusion_signal`) and target vintages (`month`, `released_at`, `value`).
The default origin is the UTC start of the following month. Feature vintages must be
available by that origin; an optional `forecast_at` column supplies actual origins.
The earliest valid forecast per month is retained. Historical training targets use the latest version released
by the current origin; the test target uses its first release. If the target was
already released at the origin, it is not scored as a nowcast. A minimum of twelve
released training months is required. No official target series is bundled or fetched.

## Remaining validation before research claims

Check independent-feed provenance and scanner timing; obtain coverage and opening
states; examine matching/pack histories; select grocery categories and defensible
weights; acquire official target vintages; run longer historical folds and sensitivity
analyses. Successful synthetic recovery validates software behavior, not production
economic conclusions.
