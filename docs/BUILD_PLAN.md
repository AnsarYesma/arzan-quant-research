# Full research project completion checklist

Objective: build the complete project before the full historical data arrives.
Scope follows `../../arzan_quant_project_data_requirements.md` in the workspace and
the research sequence in README. Real-data findings remain conditional on data
readiness; synthetic runs must exercise every implemented branch.

## Deliverables and evidence

- [x] Unified multi-export ingestion: hash/size/row-count verification, immutable
  run provenance, overlap deduplication, conflict rejection, incremental API landing.
- [x] Daily panel with opening state, explicit gaps, availability, promotions,
  crawl coverage, metadata/mapping limitations and configurable eligibility.
- [x] Strict and high-confidence cross-retailer matching, pack comparisons,
  source-barcode validation, feed-family exclusions and timing diagnostics.
- [x] Lag-only features for retailer, city, category and competitor spillovers.
- [x] Non-diffusion baselines, discrete-time hazard, marked point-process model,
  and conditional magnitude model with documented assumptions and diagnostics.
- [x] Chronological walk-forward training/evaluation with leakage tests, calibration,
  event/magnitude metrics, matching/promotion/outage robustness variants.
- [x] Promotion separation and persistence summaries without future-label leakage.
- [x] Grocery price index with explicit basket/weights, eligibility, coverage and
  composition diagnostics; distinguish it from official inflation.
- [x] Release-aware monthly inflation nowcast against supplied target vintages,
  benchmark comparison and an insufficient-history gate.
- [x] Reproducible research report and interactive aggregate propagation network.
- [x] Synthetic export/coverage/opening-state/target-vintage generator with known
  directional effects, independent null, gaps, promotions and mapping edge cases.
- [x] Documented CLI/configuration, input contracts, methodology, operational workflow,
  install/build checks and an end-to-end synthetic run plus August compatibility run.

## Completion rule

Check each item only after implementation and direct verification. Tests must cover
the relevant behavior, not just successful execution. Missing production history
should produce a documented readiness gate, while synthetic fixtures prove the
modeling/evaluation paths function. Do not call model performance established on
production data until chronological real-data evaluation supports it.

## Completion audit — 13 September 2026

The pre-data software objective is complete. Production empirical conclusions are
not part of this completion claim and remain subject to the documented input gates.

| Requirement | Current implementation and direct evidence |
| --- | --- |
| Ingestion and provenance | `warehouse.py`, `manifest.py`, `landing.py`, `cli.py`; manifest tests, overlap/conflict and metadata-order tests, API-failure atomicity and landing round-trip tests. |
| Opening state and observability | `warehouse.construct_panel`; explicit opening-file test, future-opening rejection, outage/invalid-state tests, unknown-day and timezone tests. |
| Matching and feed controls | `features.py`; source-barcode independence, shared-family exclusions and duplicated-source-store kernel invariance tests. |
| Past-only features | `features.py`; append-future-data invariance test and source-date audit; executed retailer/city/category/competitor features in synthetic runs. |
| Models | `models.py`; recovery of known logistic coefficients and magnitude slope, finite probability tests, persisted converged fold fits. Marked model is explicitly a daily binned intensity model. |
| Chronological evaluation | `evaluation.py`; future-data invariance of first-fold fitting, history gates, calibration and held-out metrics; all three robustness variants execute. |
| Promotions | `analytics.promotion_diagnostics`; incomplete/invalid follow-up censorship test and synthetic seven-day follow-up summaries. |
| Index | `analytics.price_index`; known 100→110 index test, invalid-price/zero-weight-coverage gate; 240-day synthetic basket run. |
| Inflation evaluation | `nowcast.py`; release/revision invariance tests, insufficient-history gate, end-to-end monthly branch, monthly-feature vintage extraction and backdating rejection. |
| Reporting and network | `reporting.py`; generated Markdown/PNG/HTML, browser smoke test exercises both filters without script errors, final screenshot inspected. |
| Synthetic controls | `fixtures.py`; known Alpha→Beta recovery, independent-null edge test, separate monthly index/diffusion target simulation and revisions. |
| Packaging and operations | 31 tests pass; lint and format checks pass; wheel/source archives build; wheel installed without dependencies into an isolated environment and console entry point runs. Archives checked to exclude raw data and credentials. |

Final reproducible artifacts:

- `artifacts/research-ready/`: daily synthetic pipeline, all robustness branches,
  and a separate 48-month synthetic target-vintage experiment (36 held-out months).
- `data/private/research-ready/`: August compatibility run, 1,335,618 observations
  and 4,858,508 daily states. No historical mapping validity or adequate evaluation
  history is fabricated; model and nowcast gates behave as expected.
- `artifacts/packages/`: installable wheel and source archive. Package Python source
  bytes match the current working source. The source archive includes operating
  instructions and configuration.

Both final runs' recorded artifact hashes and Python source hashes were checked
against current files. The synthetic hazard improves Brier score modestly relative
to its baseline; its return MAE does not improve. Both outcomes remain visible in
the report. Synthetic performance is not evidence about Kazakhstan production data.

## Data-dependent work after delivery

Supply additional exports, coverage/opening state, appropriate mapping/metadata
vintages, verified grocery category IDs and official target vintages. Then run the
same pipeline and inspect its diagnostics before making economic claims. Memory
requirements of the in-memory modeling matrix must be assessed on the eventual full
dataset; no untested multi-year throughput claim is made.


## Full-data research audit — 14 September 2026

The delivered-history study is complete as a retrospective empirical analysis.
It does not establish successful real-time prediction, a causal propagation model,
or a validated official-inflation nowcast.

- All 84 Parquet files and 87 supplementary checksum entries were verified.
  Actual Parquet row counts and manifest totals reconcile to 17,064,305 observations.
- The complete export produced 36,167,465 daily states, 2,303,355 eligible daily
  transitions, and 1,990,575 matched model targets, without sampling.
- Nine chronological test windows cover 1,988,367 held-out primary transitions.
  Primary and barcode/no-promotion/recent-state sensitivity evaluations completed.
- The primary diffusion Brier score is 0.291425 versus 0.290189 for the hazard
  baseline and 0.081972 for no change. Diffusion also worsens Brier error relative
  to its baseline in each pooled sensitivity comparison. Negative findings remain
  prominent in the final report.
- An additional analyst-defined grocery-target evaluation uses 142 food-category
  IDs; its exact scope and separate fitted results are retained.
- Event-level auditing finds 15,438,970 availability-only movements, or 90.48% of
  retained rows. The event mixture shifts markedly in April. This diagnostic does
  not retroactively alter training samples or labels.
- Index readiness is limited to 11 opening offers and 19 eligible days out of 324.
  Missing official target vintages and historical feature vintages remain an explicit
  unsupported empirical objective, not a claimed successful nowcast.
- Feature construction now joins prior-day evidence to eligible outcomes instead
  of sorting/copying every carried state. Four synthetic feature-equivalence checks
  pass against the preceding implementation at 1e-12 numeric tolerance.
- Sparse categorical matrices preserve the dense design and model objective while
  making full-history estimation practical. Dense/sparse regression checks pass.
- Failed attempts are archived; panel recovery verifies inputs, settings and panel
  code and records a checkpoint hash. A resumed/fresh equivalence test passes.
- 34 tests pass; source, tests and supplementary tools pass lint and formatting.

Delivery paths:

- `data/private/full-history-final-20260914/`: verified primary/robustness run,
  models, predictions, reconstructed database and immutable attempt history.
- `data/private/full-history-grocery-20260914/`: grocery-target model evaluation.
- `data/private/full-history-review-20260914/`: integrated findings, figure,
  interactive dashboard and evidence hashes.
- `data/private/full-history-audit-20260914.json` and
  `data/private/full-history-event-regimes.json`: aggregate export/event audits.
- `artifacts/packages-full-history/`: refreshed installable wheel and source archive;
  these supersede the earlier pre-data package files.


## Corrected empirical study complete — 15 September 2026

The owner-confirmed continuous-observation assumption is implemented and the full
study has been refitted. The primary result is essentially a tie: diffusion Brier
error is +0.076% versus baseline; barcode +0.050%, no-promotions +0.095%, grocery
+0.198%. The paired daily uncertainty interval spans zero. The dramatic April
sampling artifact is removed, but a reliable incremental daily forecasting
advantage is not established. The tests cover the selection correction, equivalent
memory-scaled evaluation, synthetic controls, and the paired score audit.

The integrated findings and dashboard are in
`data/private/continuous-review-20260915/`. Version 0.1.1 packages in
`artifacts/packages-continuous-history/` supersede older distributions. Earlier
study artifacts remain preserved. Official inflation forecasting remains
unvalidated; the small illustrative index is not an official CPI estimate.
