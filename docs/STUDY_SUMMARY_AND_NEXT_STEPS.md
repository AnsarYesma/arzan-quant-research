# Arzan: quick study report and next steps

Date: 15 September 2026. Status: corrected study complete; the extensions below are
implemented and tested, with their full-history rerun kept separate from the
superseded results in this note.

## Finding

The study finds weak descriptive alignment between retailers, but no clear overall improvement in daily price-change prediction from the tested diffusion features. This does **not** establish that price changes never propagate: within-day responses, longer delays, nonlinear reactions and particular retailer/product groups remain open questions.

The corrected analysis assumes continuous crawler coverage, as specified by the owner. Quiet days retain unchanged prices instead of becoming unobserved after seven days. This fixes a material eligibility problem, expands model targets from 1.99 million to 19.77 million, and removes the dramatic artificial April break. Earlier selected-sample results are superseded.

## Results

Nine chronological test windows contain 19,213,703 held-out observations; the observed daily change rate is 3.83%.

| Model | Brier error ↓ | Log loss ↓ |
| --- | ---: | ---: |
| Historical training frequency | 0.036881 | 0.162934 |
| Baseline logistic regression | 0.036140 | 0.153929 |
| Logistic regression with diffusion features | 0.036167 | 0.153774 |
| Poisson intensity model | 0.036101 | 0.153545 |

- Adding diffusion features worsens overall Brier error by **0.076%**, while improving log loss by approximately **0.100%**: the metrics are mixed.
- Diffusion improves Brier error in **6 of 9 windows**. The paired Brier difference has a seven-day block-bootstrap 95% interval of **[-0.000206, +0.000366]**, including zero. This interval is conditional on the fitted specification and concerns Brier error only.
- Grocery targets show **0.198% worse** Brier error with diffusion features. Barcode and supplied-promotion-flag sensitivities also show small overall deterioration.
- Unadjusted change rates are **3.85% without** recent peer activity and **3.89% with** it. Among directional target changes following peer activity, **51.93%** agree in direction, versus a **50.07%** benchmark from independent marginal directions. These are descriptive associations, not causal estimates.
- **39 tests passed**, including injected propagation recovery, independent controls, quiet-day eligibility and past-only features. This supports implementation correctness, not completeness of the economic model.

## What was modeled

The main model is L2-regularized logistic regression predicting whether a store's product price changes between consecutive eligible end-of-day states. Baseline predictors include retailer, city, category, weekday, lagged return, lagged promotion and time since the last recorded update. The diffusion version adds competitor, cross-city and category activity from the preceding three days.

The study also fits a daily Poisson intensity model and a ridge regression for signed log return conditional on a change. The Poisson model includes decaying activity features but is **not a fitted continuous-time Hawkes process**. Its score cannot isolate diffusion's contribution because it also changes model family.

Current limitations include no product/store fixed effects, no explicit competitor price-gap predictor, a short exposure window and mostly linear effects. Recorded-update age can reset on an availability event; it is not necessarily time since the last actual price change. Daily net prices can hide intraday changes and reversals.

## Would Hawkes perform better?

Possibly, but this is untested. A marked multivariate Hawkes model could estimate how price changes at one retailer alter subsequent event intensity at others, with response delays and separate effects for increases and cuts.

Start with frequently repriced, well-matched products and regularized retailer interactions. Include changing background repricing rates and account for common shocks; apparent excitation alone does not establish causality. Use actual price-change events, excluding availability-only updates. Check whether timestamps represent price changes or collection times: complete coverage does not guarantee exact event timing. If resolution is coarse, use a binned or interval-aware approach. See [Coarse-Grained Hawkes Processes](https://pmc.ncbi.nlm.nih.gov/articles/PMC12191576/).

## Implemented next steps

1. **Improved predictors.** The pipeline now builds prior-day matched-peer price gaps,
   cheapest status, priced-peer coverage, time since the last actual own-price change,
   7/30/90-day own repricing rates and 1/3/7/14-day peer-activity windows. Tests verify
   that appending future changes cannot alter past features.
2. **Paired boosted-tree comparison.** Fixed depth-two histogram-gradient-boosted trees
   are evaluated with and without competitor features beside the corresponding logistic
   models. Training-only encoding and deterministic sampling are recorded per fold.
3. **Response timing and heterogeneity.** The run now reports 1–14-day response profiles,
   directional agreement, retailer/category slices, a calendar-group adjustment and an
   isolated-event view that removes overlapping source events.
4. **Focused excitation experiment.** Frequently repriced multi-retailer products receive
   a same-risk-set daily Poisson comparison with and without cross-retailer excitation,
   plus a raw-timestamp resolution audit. It is labeled coarse-grained rather than a
   continuous-time Hawkes result.
5. **Fixed evaluation protocol.** Brier error is primary; log loss and calibration are
   secondary. All comparisons retain expanding chronological folds and identical risk
   rows within model family. These results remain exploratory because the historical
   windows were previously inspected.

The implementation followed the stated priority: better features and boosted trees
first, then the focused excitation comparison. Do not select a model simply because
it produces a positive propagation result.

## Extension results

The full corrected-history rerun retains 19,213,703 held-out observations. In the
logistic family, competitor features improve Brier error from **0.035968** to
**0.035870** (-0.273%) and improve log loss by 0.321%, with better Brier error in
6 of 9 windows. The paired seven-day block-bootstrap interval for the Brier
difference is **[-0.000367, +0.000247]**, however, so the primary-metric result is
not stable enough to establish incremental predictive value.

The boosted baseline without competitor features has the best pooled Brier error,
**0.035770**. Adding competitor features worsens it to **0.035997** (+0.635%), with
improvement in 4 of 9 windows. Its paired Brier interval is **[+0.000010,
+0.000455]**, entirely on the worse side, although log loss improves by 0.248%.
The metrics again disagree.

On the focused 100-product excitation subset, adding cross-retailer excitation
worsens Brier error by 0.327% and log loss by 0.607%, improving Brier error in only
3 of 9 windows. The 1–14-day adjusted response profile is non-monotone; isolated
events peak at 7 and 14 days, consistent with calendar cadence as an alternative
explanation. Raw timestamps have within-day variation, but remain collection times,
so no continuous-time or causal claim is warranted.

Overall, stronger own-history features and nonlinear prediction improve on the old
baseline, but incremental competitor information remains model-dependent and
unstable. The defensible conclusion remains negative: there is no validated overall
price-contagion signal.

## CV positioning

The defensible contribution is building and auditing a large retail-price panel,
correcting observation-selection bias, and evaluating incremental predictive information
with linear, nonlinear and event-timing approaches across chronological holdouts. Do not
claim causal contagion, trading profitability or validated inflation forecasting. The
current price index uses only 11 opening-basket offers, and the inflation nowcast has no
validated result.

## Existing evidence

- [Published aggregate results](RESULTS.md)
- [Reproduction and methodology](CONTINUOUS_HISTORY.md)
- [Observation-assumption audit](OBSERVATION_ASSUMPTION_AUDIT.md)
- [Methods and interpretation](RESEARCH_METHODS.md)

The linked private outputs remain local project evidence; this note does not publish the underlying data.
