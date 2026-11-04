# Phase 5: Adriyala baseline comparison workflow

Implemented 4 November 2026 after Phase 4 was committed and pushed as `60d988fed132f8dbc72383c60903a64b8d1dd06b`. Phase 5 is recorded in a separate subsequent commit on `main`. Package version is 0.5.0; dependencies remain NumPy 2.4.6 and Matplotlib 3.10.8.

The available-data implementation provides a fixed-parameter station comparison pipeline and an explicitly approximate audit of the published Adriyala profiles. **Exact Adriyala baseline reproduction is incomplete**: the supplied PDFs do not contain the needed numeric station coordinates, raw measurement table, survey transform or complete datum/stage/convention metadata. No model-generated data has been presented as a measured mine observation.

## Approximate comparison available now

MTP PDF p.24–26 were visually checked again. Pages 25 and 26 provide observed mine and reported fitted/predicted curves versus distance along S11–S58 and S61–S99. Their distance axes cannot be mapped to global station x/y from the supplied material with established survey accuracy. The plan allows an approximate digitized comparison when raw data is missing, while keeping exact reproduction incomplete.

The tracked `data/adriyala_digitized/report_traces.json` contains sparse manual pixel picks for both left-axis subsidence curves, plot-border/distance calibration, page references, source PDF/image hashes, assumed reading bounds, method and limitations. Curved-page calibration is explicit and approximate. The right-axis estimated-strain curve is excluded. Source-pixel overlays were inspected; overlapping traces and the testing line's steep recovery were checked at enlarged scale before accepting the picks.

Run:

```powershell
.\.venv\Scripts\python.exe -m subsidence audit-report-profiles data/adriyala_digitized/report_traces.json --output outputs/adriyala_published_audit
```

| Published line | Role in source | Comparison sample count | Digitized-curve RMSE (m) | Reported RMSE (m) |
| --- | --- | --- | --- | --- |
| S11–S58 | Fitting | 45 | approximately 0.249 | approximately 0.25 |
| S61–S99 | Testing | 40 | approximately 0.253 | approximately 0.26 |

These are **published-curve audit metrics**, not rebuilt-engine station errors. The current engine is not evaluated in this path. The 10 m comparison samples are interpolated within the common trace-distance interval, not original station identities or spacing. The fitting sample interval is 0–440 m and testing 10–400 m; no trace is extrapolated beyond their common overlap.

Assumed bounds are ±0.05 m per curve vertically and ±10 m in distance. The corresponding vertical-only RMSE diagnostic range is `[max(0,RMSE-0.10), RMSE+0.10]` m by the norm bound on residual perturbations. It omits distance, scan-calibration and sparse-tracing uncertainty. These bounds are assumptions about reading the scan, not confidence intervals or measured observation uncertainty. Internal numeric precision is retained for replay; it does not imply comparable measurement precision.

The local generated bundle is `outputs/phase5_adriyala_baseline`. Earlier exploratory plot crops/audits under other Phase 5 review output paths are superseded by this inspected bundle. The definitive tracked pixel input is the current report_traces.json.

| Audit artifact | Contents |
| --- | --- |
| `baseline_report.md` | Approximate fit/test comparison, source metrics and explicit missing inputs |
| `audit_summary.json` | Metrics, assumed bounds, evidence status and incomplete-reproduction flags |
| `digitized_comparison.csv` | Common-distance observed/reported-prediction/residual values, without station IDs or global x/y |
| `digitized_trace_points.csv` | Raw source-pixel picks and calibrated per-trace distances/Uz |
| `published_line_NNN.png` / `.svg` | Digitized profiles/residuals and assumed reading bounds |
| `published_line_NNN_pixel_audit.png` / `.svg` | Picked pixels over the original graph and plot-border calibration |
| `digitization.json` | Replayable manifest referring to copied sources |
| `original_digitization_manifest.json` | Original manifest bytes |
| `sources/` | Source-page PNGs and PDF, with original hashes preserved |

Re-running `audit-report-profiles <archived-output>/digitization.json --output <new-path>` reproduces the same audit metrics. Source hash mismatches are rejected. No automatic curve tuning is done to match the reported RMSE.

## Station comparison ready for supplied measurements

`evaluate-stations` loads measured coordinates and Uz, predicts at those coordinates using a single frozen model, and exports residuals and comparison figures. It supports the existing flat and inclined models. Use the Adriyala inclined settings to preserve the manual baseline p=1.3 m and beta=20 degrees under the explicit Phase 4 convention.

```powershell
.\.venv\Scripts\python.exe -m subsidence evaluate-stations examples/adriyala_geometry.json --model examples/adriyala_inclined_model.json --observations path/to/stations.csv --metadata path/to/metadata.json --output outputs/adriyala_station_baseline
```

This command requires actual data. `examples/adriyala_observations.template.csv` is intentionally header-only, and `examples/adriyala_observations.template.json` leaves unknown metadata null. They cannot run successfully without sourced values.

CSV columns:

| Column | Requirement |
| --- | --- |
| `station_id` | Required nonempty identifier; unique across the dataset, including fit/test groups |
| `line_id` | Required declared monitoring-line ID |
| `x_m`, `y_m` | Required finite coordinates already in the model's global metre frame |
| `uz_observed_m` | Required finite measured value, interpreted using declared vertical sign |
| `distance_m` | Optional nonnegative line distance; complete and unique within a line when supplied |
| `uncertainty_m` | Optional nonnegative measurement uncertainty, retained but not used as metric weights |

Unknown/duplicate headers, invalid numbers, inconsistent row widths, duplicate IDs, missing declared lines, and partial/duplicate/negative distance columns are rejected. UTF-8 with or without BOM is supported. Raw input bytes and row order are retained.

Metadata version 1 uses `units={"length":"m"}` and requires name, evidence, vertical_sign, coordinate_reference, vertical_datum, measurement_stage, provenance, and line_roles. Evidence must be `field_measurements`, `digitized_with_survey_coordinates`, or `synthetic_verification`. Both fit and test line roles must be present. The Adriyala template assigns S11–S58 to fit and S61–S99 to test. These are historical roles, not a fitting operation in this phase.

`vertical_sign=up_positive` retains the observed value; `settlement_positive` negates it into canonical global Uz. The original value is exported as uz_input_m. The only preprocessing is this declared sign conversion. No datum shifts, exclusions, robust losses, amplitude changes, or parameter fitting occur. Numeric measurements are not synthesized from station IDs or line distances.

If supplied distances are unavailable, figures use station identifiers in original CSV order. They do not fabricate a distance axis or infer a station sequence. Datum, origin/orientation and measurement stage must be documented by the data provider; there is no automatic survey transform or time model. Predictions use the project's configured horizontal surface elevation.

One solver call evaluates all supplied coordinates, including off-grid locations, with the same model for both groups. Changing the observation display grid does not change fixed-station predictions. Model p/Smax/influence-angle settings are saved before any results are reported and remain unchanged.

## Metrics, outputs and Python API

For each station, error is `predicted global Uz - observed canonical global Uz`. All metric units are metres:

```text
RMSE = sqrt(mean(error^2))
MAE  = mean(abs(error))
Bias = mean(error)
```

Metrics are computed per monitoring line and per fit/test role using all observations, without weighting. Reported RMSE values can be supplied by line only when a source is documented. Their differences from computed errors are descriptive values, not automatic proof of original reproduction. Minimum observed/predicted Uz is also retained. No percentage-accuracy target or automatic success label is inferred from proximity to a rounded reported number.

```python
from subsidence import load_project, load_model, load_observations, evaluate_stations

project = load_project("examples/adriyala_geometry.json")
model = load_model("examples/adriyala_inclined_model.json")
data = load_observations("path/to/stations.csv", "path/to/metadata.json")
baseline = evaluate_stations(project, model, data)
print(baseline.line_metrics, baseline.role_metrics)
```

Station bundles contain project/model snapshots, `raw_observations.csv`, original metadata bytes, normalized `observation_metadata.json`, station-level `station_results.csv`, numeric `station_predictions.npz`, `baseline_summary.json`, line plots, and `baseline_report.md`. The CSV retains raw/canonical observation signs, predicted Ux/Uy/Uz, residual, optional distance/uncertainty, measurement stage and evidence. JSON includes model settings, provenance, hashes, exact coordinate-evaluation policy and explicit no-fitting/original-reproduction flags. File stems are numbered; user-supplied line names never become paths. Existing output folders must be new/empty.

## Verification and current completion status

All **125 tests** pass, retaining the prior 102 and adding 23 Phase 5 tests. They cover known RMSE/MAE/bias, positive-settlement conversion, raw-byte retention, malformed/missing metadata, split/ID validation, direct off-grid predictions, display-grid independence, one frozen call for both groups, flat/inclined dispatch, source hashes/calibration rejection, archived audit replay, and station/CLI exports.

```powershell
.\.venv\Scripts\python.exe -m subsidence verify-baseline --output outputs/baseline_verification
```

The local `outputs/phase5_verification` has **9 passing synthetic checks**. Explicit synthetic observations 1,2,3,4 m in positive-settlement convention are compared with a zero-amplitude model at fractional coordinates. Known fit metrics are RMSE=sqrt(2.5), MAE=Bias=1.5 m; testing RMSE=sqrt(12.5), MAE=Bias=3.5 m. These deliberately artificial numbers test the data/metric pipeline and are not Adriyala measurements. A complete synthetic station bundle is retained under `synthetic_case/` for replay. Actual scan-audit overlays were also visually inspected.

Available-data Phase 5 implementation is ready, and the allowed approximate published comparison is generated. Exact Adriyala field reproduction is still incomplete. Missing inputs and remaining model-convention discrepancies are listed in `docs/ADRIYALA_DATA_INVENTORY.md` and the audit report. The 0.249/0.253 m graph-audit metrics must never be described as errors of the rebuilt solver. Phase 6 calibration must wait for appropriately located measurements or use clearly identified synthetic verification data; unlocated plot-distance samples cannot silently substitute for surveyed stations.
