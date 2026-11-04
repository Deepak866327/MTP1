# Phase 6: automatic calibration

Implemented on 4 November 2026, package version 0.6.0. This phase adds bounded automatic fitting of flat Smax or inclined p (metres) and influence angle beta (degrees), followed by a frozen held-out comparison. Geometry, the full Gaussian, depth/area conventions and the inclined reconstruction remain as documented in Phases 1–4.

The calibration software and synthetic verification are complete. **Adriyala calibration remains pending real station coordinates, measured Uz, datum/sign/stage metadata and justified site bounds.** Published graph distances without a surveyed coordinate transform cannot be passed to the spatial solver as station positions. This phase does not establish reproduction of the original engine or an improvement in mine-prediction accuracy.

## Run locally

From the project directory in PowerShell, update the environment and generate synthetic calibration examples:

```powershell
.\.venv\Scripts\python.exe -m pip --use-feature=truststore install -r requirements.txt
.\.venv\Scripts\python.exe -m subsidence verify-calibration --output outputs/my_phase6_verification
```

Open `outputs/my_phase6_verification/verification.md`. Each case contains settings, fit/test plots, residuals, a comparison with the supplied manual settings and optimizer diagnostics. Output paths must be new or empty. Synthetic station inputs are generated beside each case and can be used to run the normal calibration command:

```powershell
.\.venv\Scripts\python.exe -m subsidence calibrate-stations outputs/my_phase6_verification/inclined_independent_inputs/project.json --model outputs/my_phase6_verification/inclined_independent_inputs/manual_model.json --observations outputs/my_phase6_verification/inclined_independent_inputs/observations.csv --metadata outputs/my_phase6_verification/inclined_independent_inputs/metadata.json --settings examples/calibration_settings.synthetic.json --output outputs/my_inclined_calibration
```

The fitted model is an ordinary model JSON, usable by existing commands. Re-evaluate it without fitting:

```powershell
.\.venv\Scripts\python.exe -m subsidence evaluate-stations outputs/my_inclined_calibration/project.json --model outputs/my_inclined_calibration/fitted_model.json --observations outputs/my_inclined_calibration/fitted_evaluation/raw_observations.csv --metadata outputs/my_inclined_calibration/fitted_evaluation/raw_metadata.json --output outputs/my_frozen_evaluation
```

To predict displacement/strain maps with the fitted settings, pass `fitted_model.json` to the corresponding `solve-flat`, `solve-inclined`, `deform-flat` or `deform-inclined` command with the saved project.

Python API:

```python
from subsidence import (
    calibrate_stations, load_calibration_settings, load_model,
    load_observations, load_project,
)
from subsidence.phase6_results import export_calibration

result = calibrate_stations(
    load_project("project.json"), load_model("manual_model.json"),
    load_observations("stations.csv", "metadata.json"),
    load_calibration_settings("calibration_settings.json"),
)
export_calibration(result, "outputs/new_calibration")
```

## Input and bounds contract

Station CSV and metadata follow Phase 5, including explicit coordinate reference, datum, sign, measurement stage, provenance and `line_roles`. Only observations assigned `fit` enter optimization. At least three fit stations are required for two parameters; this count alone does not establish identifiability. For the intended Adriyala comparison, assign the independently located S11–S58 line to `fit` and S61–S99 to `test` before running.

`examples/calibration_settings.synthetic.json` demonstrates the strict version-1 settings format:

| Setting | Meaning |
| --- | --- |
| `units` | Exactly `{"amplitude":"m","angle":"degrees"}` |
| `amplitude_bounds_m` | Finite lower/upper bounds, 0 <= lower < upper |
| `influence_angle_bounds_deg` | Finite bounds strictly inside (0, 90) degrees |
| `initial_guesses` | At least two distinct amplitude/angle objects, strictly inside bounds |
| `bounds_basis` | `synthetic_demonstration` or `documented_site_information` |
| `bounds_justification` | Required explanation of both physical/site or synthetic bounds |
| `max_nfev` | Positive integer, per start; default 200 |
| `ftol`, `xtol`, `gtol` | Explicit stopping tolerances; defaults 1e-10 |

Unknown/duplicate JSON keys, nonfinite numbers, boolean numeric values, wrong units and unsupported schemas are rejected. The manual comparison model may lie outside fit bounds; it is evaluated as supplied and is not an optimizer starting guess unless explicitly included in settings.

The demonstration uses amplitude 0..3.5 m and beta 10..40 degrees with three starts: (0.4 m, 12°), (1.3 m, 20°), (2.8 m, 36°). Its illustrative extraction-height bound and deliberately bracketed synthetic truth do not establish Adriyala physical bounds. Demonstration bounds are rejected for field or surveyed-digitized evidence.

For field use, independently justify both bounds from site information, extraction height, the selected amplitude convention and engineering knowledge; set `bounds_basis` to `documented_site_information` and record that reasoning/source in `bounds_justification`. The source reports 3.5 m extraction height and manual p=1.3 m, beta=20°, but does not establish a calibrated admissible beta interval. Software validates the supplied declaration and numbers; it cannot certify the physical justification. Do not choose bounds from held-out outcomes or treat p as a dimensionless coefficient.

## Objective and held-out policy

For fit-role station i, the residual is

`r_i = predicted global Uz(x_i, y_i; amplitude, beta) - observed canonical global Uz_i`.

The saved objective is `SSE = sum(r_i**2)` in m². SciPy's optimizer cost is SSE/2. Optimization is unweighted, with linear loss and no additional fitted offsets. The same sign conversion as Phase 5 is applied on ingestion. No station is excluded, snapped to a grid, shifted in datum, or spatially relocated. Optional measurement uncertainty is retained but does not change weights.

`scipy.optimize.least_squares` uses bounded trust region reflective optimization (`trf`), three-point finite-difference Jacobians and parameter scales equal to declared bound widths. All supplied starts run deterministically. The converged run with the smallest **fit-only** SSE wins; an exact tie uses the earliest supplied start. The model's amplitude and beta are replaced while its other conventions remain fixed.

The objective receives only fit-role coordinates and observed Uz. Test observations, test coordinates, published RMSE and uncertainty values do not choose starts, bounds, weights, a winning run or a stopping decision. After selection, the fitted model is frozen and evaluated at all exact station coordinates. The supplied manual model is evaluated separately using the same dataset. RMSE, MAE and bias are exported by line and role, including the signed fitted-minus-manual RMSE difference. A manual file is a supplied baseline; it represents the source's original manual choice only when its values and conventions actually match.

The held-out report describes this frozen comparison. It does not automatically assert a general accuracy improvement. If test results guide later changes, obtain a new independent evaluation set. Repeated synthetic checks are software verification, not new field evidence.

## Convergence, failed starts and identifiability

Every start records parameters, convergence status/message, SSE, function/Jacobian counts, optimality, active bounds and every objective evaluation, including numerical Jacobian perturbations. The trace is therefore not a sequence of accepted optimizer iterates and need not decrease monotonically. `max_nfev` follows SciPy's function-evaluation convention; actual recorded calls include finite-difference calls.

Unconverged runs are excluded from selection and retained with a warning. If no start converges, the CLI returns 1, saves the inputs and failed attempts, selects no fitted model and does not evaluate held-out data. Invalid input returns 2. A converged fit returns 0, including when diagnostic warnings require review; numerical convergence does not imply scientific adequacy. The Python API raises `CalibrationFailure` with `.attempts` when all starts fail.

The selected fit saves its residual vector, raw Jacobian and column units, bound-scaled singular values, numerical rank, condition number and sensitivity-column cosine. Scaling by bound widths permits a declared metre/degree comparison; these diagnostics still depend on those bounds. Warnings flag:

- rank below two, scaled condition number > 1e4, or absolute sensitivity-column cosine > 0.995;
- a fitted value within 1e-6 of a bound width from either limit;
- successful starts differing by > 1e-4 of a bound width;
- any failed starts.

These thresholds are recorded heuristics. No confidence interval or statistical parameter uncertainty is inferred. Good local conditioning and agreeing starts do not prove a unique global solution. Repeated points or a poorly placed line may not distinguish amplitude from spread, even with many measurements. The tests explicitly exercise this case.

## Saved bundle

| Artifact | Purpose |
| --- | --- |
| `project.json`, `manual_model.json`, `fitted_model.json` | Fixed geometry, comparison settings and replayable selected settings |
| `calibration_settings.json` | Bounds, justification, starts and tolerances |
| `optimizer_attempts.json`, `objective_trace.csv` | Every start, outcome and objective call |
| `calibration_summary.json` | Selected SSE/residual vector, Jacobian diagnostics, source hashes, role/line comparisons and evidence limits |
| `calibration_diagnostics.png/.svg` | Objective traces, supplied starts and final parameters |
| `calibration_report.md` | Parameters, manual/fit comparison, held-out metrics, identifiability and embedded line plots |
| `fitted_evaluation/`, `manual_evaluation/` | Untouched raw observation/metadata bytes, canonical metadata, station CSV/NPZ, RMSE/MAE/bias and fit/test PNG/SVG profiles |

The nested Phase 5 reports describe fixed-parameter evaluation: fitting took place in the parent Phase 6 run. Source CSV/metadata hashes and numerical library versions are recorded; model, project and canonical fit settings are saved. Existing nonempty output directories are never overwritten.

## Verification and observed results

The fixed benchmark is the Phase 2 400 m × 200 m panel at 400 m reference depth, with either zero dip or a 10° dip. Synthetic truth is amplitude 1.2 m and beta 23°. A 31-point fit transect spans y=-300..300 m at x=-35.25 m; a distinct 23-point test transect lies at x=125.75 m. Source spacing is 10 m. No observations are sampled from the display grid.

Independent flat observations use the analytical rectangle integral. Independent inclined observations use the separate global-coordinate Gauss-Legendre reference (order 48), without the production midpoint integration or seam-frame implementation. A separate production-forward flat dataset checks discrete inverse consistency; it is explicitly labeled as such.

Predeclared independent recovery tolerances are amplitude 0.002 m, angle 0.1°, and held-out RMSE 0.001 m. These allow source discretization error consistent with earlier convergence studies. The discrete consistency case uses amplitude 1e-7 m and angle 1e-5°. They are benchmark tolerances, not a general calibration accuracy promise. Discretization bias is not parameter uncertainty; other geometries/meshes need convergence checks before interpreting field parameters.

| Synthetic case | Fitted amplitude (m) | Fitted beta (degrees) | Held-out RMSE (m) |
| --- | --- | --- | --- |
| Independent flat | 1.200000091 | 23.01870828 | 3.8181e-8 |
| Independent 10° inclined | 1.200003387 | 23.01880840 | 2.3304e-5 |
| Discrete flat consistency | 1.2 | 23 | approximately zero |

All three starts converge in each case; scaled Jacobians have rank two and start differences are negligible. The small angle bias against independent references is consistent with midpoint source discretization. **These are synthetic verification results, not reproduced Adriyala results.**

The suite contains 144 tests (125 previous + 19 Phase 6). New coverage includes independent/discrete recovery, repeatability, fit-only solver coordinates, changed held-out values/coordinates/reported errors, frozen evaluation models, unweighted noisy residuals, retained uncertainty without weighting, deficient rank, active bounds, partial/all failures, strict inputs, CLI exit codes, source-byte preservation and saved-model replay. `verify-calibration` adds 18 passing synthetic acceptance checks and reviewable result bundles.

## Remaining project work

Adriyala fitting and held-out field assessment require the missing located measurements and site justification. Phase 7 remains the local interface, and Phase 8 remains the wider convergence/sensitivity/performance studies and final report. Phase 6 adds automatic calibration as a workflow improvement; it resolves none of the previously logged source-convention ambiguities.
