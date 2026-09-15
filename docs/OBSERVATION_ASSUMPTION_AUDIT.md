# Correction: continuous observation versus event-only selection

On 15 September 2026, the owner clarified that crawler coverage should be assumed
continuous, historical product mappings should be treated as acceptable, and
additional history is unavailable. The earlier full-history evaluation used a
different observation assumption. Its scores must not be used as the final answer
to the owner's intended price-propagation question.

## Confirmed mechanism

`construct_panel` reconstructed carried daily states, but the old eligibility rule
required a newly recorded event or an explicitly successful crawl record. With no
crawl file, quiet days were excluded. Outcomes also required the preceding day to
be eligible, so a genuine change after a quiet day could be excluded too. An
additional seven-day cap treated time since the last event as quote staleness.
Under continuous crawling of a change-event stream, that conflates unchanged prices
with missing observations.

Availability-only events could supply the event-day evidence needed for eligibility.
Consequently, the availability-event mix changed the composition of model targets.
This is a consequential sampling/design mismatch, not evidence of a numerical
optimizer failure. Passing implementation tests did not validate that assumption.

## Full-data, read-only diagnostic

The existing 36,167,465 daily states were reevaluated with carried states considered
observed after first entry. Prices still must be positive, finite, available and
in KZT. Known collection failures and ambiguous simultaneous records still censor
states. Product matching rules are unchanged. No pre-entry prices were invented.

| Month | Previous selected daily change rate | Continuous-observation daily change rate |
| --- | ---: | ---: |
| November 2025 | 79.56% | 5.97% |
| December 2025 | 86.08% | 4.71% |
| January 2026 | 90.25% | 4.57% |
| February 2026 | 95.32% | 4.80% |
| March 2026 | 99.98% | 4.20% |
| April 2026 | 3.54% | 3.60% |
| May 2026 | 6.18% | 2.83% |
| June 2026 | 6.01% | 3.04% |
| July 2026 | 10.53% | 4.62% |
| August 2026 | 20.17% | 3.89% |

These are monthly rates among matched eligible daily transitions, not event-stream
percentages or the earlier 30-day test-window rates. The full matched sample expands
from 1,990,575 transitions and 164,794 changes to 19,771,832 transitions and 762,022
changes. The dramatic March-to-April outcome-rate break largely disappears when
quiet days are included. The raw availability-event composition still changes, but
that alone does not establish bad data or explain a true market regime change.

## Implemented correction and verification

`assume_continuous_observation=true` is an explicit research setting. It permits
carried states and bypasses the age-since-event cap. The conservative default remains
available for datasets without the owner's coverage assurance. Known outages,
unavailable products and invalid prices still fail eligibility checks.

`configs/full-history-continuous.json` enables the owner's assumption and retains
retrospective matching. Tests verify ten quiet days followed by a genuine price
change, no invented pre-entry states, and continued outage/unavailability censoring.
All 36 tests pass. The previous completed runs are preserved without changing their
recorded results or hashes.

Reproduce the diagnostic from the project root:

```sh
PYTHONPATH=src .venv/bin/python tools/audit_observation_assumption.py
```

The full monthly counts are in
`data/private/observation-assumption-audit/monthly_comparison.json`.

The primary models have now been refitted on 19,213,703 held-out observations.
Diffusion Brier error is 0.036167 versus 0.036140 for the baseline, approximately
0.08% worse overall. Diffusion improves 6 of 9 chronological windows, including the
last five. The seven-day block-bootstrap 95% interval for diffusion minus baseline
Brier error is [-0.000206, 0.000366], spanning both improvement and deterioration.
Predicted diffusion frequency is 4.01% versus 3.83% observed: the severe calibration
problem is gone, but a reliable incremental daily forecast advantage is not established.

Robustness and grocery-only refits are complete. Barcode matching gives +0.05%
Brier error versus baseline, excluding flagged promotions +0.09%, and grocery
targets +0.20%. These results do not establish a reliable incremental daily
forecasting advantage. See
[the corrected-run design](CONTINUOUS_HISTORY.md). This daily design does not test
within-day propagation or establish a causal effect.
