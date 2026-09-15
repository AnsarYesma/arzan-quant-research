# Published aggregate results

The corrected panel contains 19,771,832 eligible targets and 762,022 daily price
changes. Nine chronological holdouts contain 19,213,703 observations. Production
rows, product mappings, prediction files, and fitted research databases remain
private under the data owner's publication policy.

## Model comparison

| Model | Brier error | Log loss |
| --- | ---: | ---: |
| Historical training frequency | 0.036881 | 0.162934 |
| Improved logistic baseline | 0.035968 | 0.152166 |
| Logistic with competitor features | 0.035870 | 0.151678 |
| Boosted-tree baseline | 0.035770 | 0.152849 |
| Boosted tree with competitor features | 0.035997 | 0.152470 |
| Daily Poisson intensity | 0.035790 | 0.151369 |

Competitor features improve logistic Brier error by 0.273%, but the paired seven-day
block-bootstrap interval for the absolute difference is [-0.000367, +0.000247],
including zero. In the boosted-tree family they worsen Brier error by 0.635%; its
interval is [+0.000010, +0.000455], entirely on the worse side.

On a focused 100-product subset, cross-retailer excitation worsens Brier error by
0.327% and log loss by 0.607% versus a time-varying baseline. The adjusted 1–14-day
response profile is non-monotone and peaks around weekly horizons, consistent with
calendar repricing cadence as an alternative explanation.

## Interpretation

Stronger own-history features and nonlinear prediction improve on the earlier
baseline. Incremental competitor information remains unstable and model-dependent,
so the analysis does not validate causal price contagion. Timestamp variation also
does not resolve whether recorded collection times are exact price-change times.

See [the methods](RESEARCH_METHODS.md), [study summary](STUDY_SUMMARY_AND_NEXT_STEPS.md),
and [publication boundary](../PUBLICATION.md).
