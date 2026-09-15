# August exploratory model run

This is a retrospective, within-August experiment, not a production validation or
a continuous-time Hawkes fit. The strict August configuration remains unchanged.

## Reproduce

From the project directory, choose a new output directory:

```sh
PYTHONPATH=src .venv/bin/python -m arzan_quant.cli run-research \
  --export arzan-quant-20260913 --settings configs/august-exploratory.json \
  --output data/private/august-exploratory-reproduction
```

The completed primary run is in `data/private/august-exploratory-v2`;
its `run.json` records completion. The first attempt is retained in
`data/private/august-exploratory` with failed status: the Poisson optimizer reached
500 iterations. The numerical iteration budget was increased to 3,000 without
changing the objective, regularization, convergence requirement, or data.

## Assumptions and scope

- Use September's frozen, high-confidence product mappings retrospectively.
  These mappings and other snapshot metadata were not necessarily available in
  August. Chronological splitting does not remove that look-ahead limitation.
- Train on August 1–21 and test once on August 22–31. The usual 60-day minimum
  is reduced to 21 days solely for this exploratory experiment.
- Keep the existing collection-evidence rules. Unknown carried-forward days
  are not treated as unchanged prices. Outcomes require eligible adjacent days.
- Because the source records change events, the resulting sample is selected
  on recorded activity. Its event frequencies and prediction scores do not
  estimate performance across all offers and calendar days.
- Retain the existing confidence threshold, fixed three-day exposure window,
  and model penalties. No parameter selection using the test period is performed.
- Feed-family exclusions are not asserted without verification. In particular,
  Small/Smallfood/Spar associations may reflect shared feeds or collection timing.
- Source-barcode matching, exclusion of promotions, and recent-state variants
  are sensitivity checks, not independent test samples. Recent-state filtering
  can be redundant when only event-day states are eligible.

## Reading outputs

`report.md` and `results.json` contain held-out scores and sensitivity checks;
`model_fits.json` contains fitted coefficients and convergence diagnostics.
`predictions.parquet` contains private row-level test predictions. The network
is a full-August descriptive association summary, not a fitted causal graph.

Compare the diffusion model against the hazard baseline to isolate the incremental
predictive value of the added signals. Compare return errors against persistence
as well: improved change probabilities need not improve price-change magnitudes.
Report calibration alongside average scores. Do not call these coefficients Hawkes
baseline, excitation, or decay parameters; decay is fixed in the daily features.

## Results

There were 93,583 eligible matched daily transitions and 18,001 net price changes.
Training used 71,201 rows with 12,892 changes; the held-out August 22–31 sample
contained 22,382 rows with 5,109 changes (22.83%). All three primary fitted models
converged: baseline in 285 iterations, diffusion in 412, and Poisson in 557.

| Model | Held-out Brier score (lower is better) | Log loss |
| --- | ---: | ---: |
| Constant training-frequency prediction | 0.178387 | 0.544233 |
| Baseline daily hazard | 0.101273 | 0.328395 |
| Hazard with diffusion signals | 0.100815 | 0.327369 |
| Daily Poisson intensity | 0.121166 | 0.368882 |

Adding diffusion signals reduces Brier error by only 0.45% relative to the hazard
baseline. The barcode-exposure variant gives a similar 0.40% reduction. Excluding
promotions reverses the result: diffusion Brier error is 0.055359 versus baseline
0.053317, a 3.83% deterioration on that variant's 15,364 held-out rows. These are
point estimates from a single split, without significance or uncertainty claims.

The primary diffusion model predicts an average change probability of 12.69%,
versus 22.83% observed in the selected test sample, indicating substantial
underprediction. Its mean absolute log-return error is 0.048929, versus 0.048207
for a zero-return prediction: it does not improve this magnitude metric.

Conclusion: the fitted baseline outperforms a constant event-rate prediction in
this retrospective sample, but August does not demonstrate a robust incremental
predictive benefit from diffusion signals. None of these findings establish causal
retailer influence, market-wide event probabilities, or out-of-month performance.

Verification: 31 tests passed after the iteration-budget adjustment; lint and
format checks passed for the modified model module.
