# Subsidence prediction project

This workspace contains the source material and rebuild plan for a surface subsidence and strain prediction project using the Influence Function Method for flat and gently inclined coal seams.

Phases 1–4, the available-data Phase 5 workflow and Phase 6 calibration software are implemented: geometry, flat/inclined displacement, global strain/profiles, station evaluation, an approximate published-curve audit, and bounded amplitude/angle fitting with held-out evaluation. Exact original-engine and Adriyala field-result reproduction remain incomplete because raw measurements, survey coordinates and some original conventions are missing.

The implementation uses Python 3.11+ with pinned NumPy, Matplotlib and SciPy. From this directory in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip --use-feature=truststore install -r requirements.txt
.\.venv\Scripts\python.exe -m subsidence validate examples/adriyala_geometry.json
.\.venv\Scripts\python.exe -m subsidence mesh examples/synthetic_flat.json --output outputs/flat_run
.\.venv\Scripts\python.exe -m subsidence mesh examples/adriyala_geometry.json --output outputs/adriyala_run
.\.venv\Scripts\python.exe -m subsidence solve-flat examples/synthetic_flat.json --model examples/flat_model.json --output outputs/flat_prediction
.\.venv\Scripts\python.exe -m subsidence verify-flat --output outputs/flat_verification
.\.venv\Scripts\python.exe -m subsidence deform-flat examples/synthetic_flat.json --model examples/flat_model.json --profiles examples/profiles.json --output outputs/flat_deformation
.\.venv\Scripts\python.exe -m subsidence sample-profiles outputs/flat_deformation --profiles examples/profiles.json --output outputs/new_profiles
.\.venv\Scripts\python.exe -m subsidence verify-deformation --output outputs/deformation_verification
.\.venv\Scripts\python.exe -m subsidence deform-inclined examples/synthetic_inclined.json --model examples/inclined_model.json --profiles examples/profiles.json --output outputs/inclined_prediction
.\.venv\Scripts\python.exe -m subsidence verify-inclined --output outputs/inclined_verification
.\.venv\Scripts\python.exe -m subsidence audit-report-profiles data/adriyala_digitized/report_traces.json --output outputs/adriyala_published_audit
.\.venv\Scripts\python.exe -m subsidence verify-baseline --output outputs/baseline_verification
.\.venv\Scripts\python.exe -m subsidence verify-calibration --output outputs/calibration_verification
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Open `preview.svg` in each output directory. Each bundle also contains the saved project, summary, source and surface CSVs, and coordinate/area arrays in `geometry.npz`. Output directories must be new or empty. Source spacing and surface spacing are separate inputs. Overlapping extraction rectangles contribute their union once; partially intersected cells use exact clipped rectangular fragments.

The synthetic example contains 800 sources and 2,000 surface points. The Adriyala example contains 5,775 sources and 10,857 surface points, reconstructed from reported geometry. These are geometry checks; the published field errors have not been reproduced.

`solve-flat` adds displacement arrays, CSV, sign/unit metadata, and `displacement_maps.png`/`.svg` to the geometry bundle. Model settings live in a separate JSON file; the synthetic example uses Smax=1 m, beta=20 degrees and full Gaussian support. The Adriyala seam is inclined and is rejected by this solver. The Python API also predicts at exact supplied surface coordinates.

`verify-flat` writes an analytical comparison, convergence tables and plots. On the fixed synthetic benchmark, maximum component error decreases from 0.00873849 m at 40 m source spacing to 0.0000340824 m at 2.5 m spacing. This verifies numerical integration, not field accuracy. Run convergence checks for other configurations before calibration.

`deform-flat` adds strain maps, arrays and CSVs, plus profiles when `--profiles` is supplied. Derivatives use actual cell-center spacing and second-order one-sided boundaries, flagged in exports; at least three centers per axis are required. Ex/Ey are dimensionless, displayed in mm/m (multiply by 1000); positive means tensile. Profiles include distance, Ux/Uy/Uz and global Ex/Ey, including on oblique lines. Endpoints must be within the cell-center domain; extrapolation is disabled.

`sample-profiles` reuses saved flat or inclined displacement arrays and derives strain without rerunning the influence solver. Edit `examples/profiles.json` or use a copy to change lines. Keep the source run with these profile exports. `verify-deformation` checks manufactured derivatives, interpolation, direct-solver comparisons, and independent analytical strain convergence. The Phase 3 benchmark reaches 0.00170846 mm/m derivative error at 5 m observation spacing; this is a synthetic numerical check.

`solve-inclined` and `deform-inclined` support seam dip from 0 to 12 degrees. The model is versioned as `inclined_seam_frame_gaussian_v1`: normal distance from observation to plane, seam-tangent Gaussian, seam-area weighting, local amplitude p/nz, and rotation of the full displacement vector back to global coordinates. Full Gaussian support is retained. These choices are documented reconstructions of incompletely specified source conventions. All **102 tests** and **27 Phase 4 acceptance checks** pass; the zero-dip solver agrees with the flat engine and the synthetic 2.5 m mesh error is about 0.033 mm against independent integration.

For a reported-geometry demonstration, use `examples/adriyala_geometry.json`, `examples/adriyala_inclined_model.json`, and `examples/adriyala_profiles.json` with `deform-inclined`. This applies reported p=1.3 m and beta=20 degrees under the explicit v1 reconstruction; it does not reproduce the reported field RMSE. Raw monitoring data is still needed for Phase 5.

`audit-report-profiles` compares digitized **published observed and published fitted/predicted curves**, without evaluating the rebuilt engine or inventing station coordinates. The approximate RMSE values are 0.249 m and 0.253 m versus source-reported 0.25 m and 0.26 m; sample counts differ from the unavailable raw station table. Source-pixel picks, calibration, hashes, assumed uncertainty and visual audit overlays are retained. This is an approximate graphical audit, not independent field reproduction.

`evaluate-stations <project.json> --model <model.json> --observations <stations.csv> --metadata <metadata.json> --output <new-directory>` evaluates the frozen model directly at supplied station coordinates. It exports predictions, residuals, RMSE/MAE/bias by line and role, plots and untouched raw inputs. CSV requires station_id,line_id,x_m,y_m,uz_observed_m; distance and measurement uncertainty are optional. Metadata must document units, vertical sign/datum, coordinate origin/orientation, stage, source and fit/test roles. The empty Adriyala templates deliberately require completion and contain no invented observations.

All **125 tests** and **9 synthetic baseline-workflow checks** pass. Phase 5's exact Adriyala reproduction remains incomplete until real station coordinates/measurements and matching conventions are available; the approximate graph audit and station workflow are ready.

`calibrate-stations <project.json> --model <manual-model.json> --observations <stations.csv> --metadata <metadata.json> --settings <calibration-settings.json> --output <new-directory>` fits amplitude (flat Smax or inclined p, metres) and beta (degrees) using only stations assigned `fit`. It runs several bounded least-squares starts, saves all objectives/statuses and identifiability diagnostics, then evaluates frozen fitted and manual settings on the held-out `test` stations. It exports a report, residual plots, raw inputs and a reusable `fitted_model.json`. Failed starts are retained; no converged start means no fitted model or test evaluation.

`verify-calibration` generates independent-reference flat/inclined synthetic recovery cases and replayable station inputs. The [Phase 6 guide](docs/PHASE6_IMPLEMENTATION.md) gives a complete calibration/replay command. [Example calibration settings](examples/calibration_settings.synthetic.json) use explicitly synthetic bounds and are rejected for field data. Actual site fitting requires documented physical bounds plus located observations; the unlocated published curves cannot supply those coordinates. **All 144 tests and 18 synthetic calibration checks pass.** Synthetic recovery establishes software behavior; Adriyala field calibration remains pending data.

- [Phase 1 implementation, conventions, and acceptance results](docs/PHASE1_IMPLEMENTATION.md)
- [Phase 2 equations, usage, and verification results](docs/PHASE2_IMPLEMENTATION.md)
- [Phase 3 strain, profiles, and verification results](docs/PHASE3_IMPLEMENTATION.md)
- [Phase 4 derivation, conventions, and verification results](docs/PHASE4_IMPLEMENTATION.md)
- [Phase 5 baseline workflow, digitization, and evidence limits](docs/PHASE5_IMPLEMENTATION.md)
- [Phase 6 calibration, held-out policy, bounds and verification](docs/PHASE6_IMPLEMENTATION.md)
- [Adriyala data inventory and missing inputs](docs/ADRIYALA_DATA_INVENTORY.md)
- [Synthetic flat-panel project](examples/synthetic_flat.json)
- [Synthetic flat-model settings](examples/flat_model.json)
- [Example profile definitions](examples/profiles.json)
- [Synthetic inclined geometry](examples/synthetic_inclined.json) and [inclined settings](examples/inclined_model.json)
- [Reported Adriyala geometry project](examples/adriyala_geometry.json)

The original project and the complete rebuild plan are described in:

- [Project understanding and phase-by-phase plan — Word](docs/Subsidence_Project_Understanding_and_Rebuild_Plan.docx)
- [Project understanding and phase-by-phase plan — PDF](docs/Subsidence_Project_Understanding_and_Rebuild_Plan.pdf)
- [Editable plan — Markdown](docs/PROJECT_UNDERSTANDING_AND_REBUILD_PLAN.md)
- [Durable project memory](PROJECT_MEMORY.md)
- [Reported Adriyala inputs, with unresolved conventions](docs/adriyala_reported_inputs.json)

The plan and its Word/PDF copies are the 3 November planning documents. The Phase 1–6 implementation notes and project memory record the current implementation status. The main plan includes the original model and software features, equations, case-study parameters, reported validation results, reproduction gaps, modest improvements, suggested architecture, and nine implementation phases with acceptance criteria.

Source OCR and upright page images are in docs/source_extracts. OCR is imperfect; precise equations and values should be checked against the images and original PDFs.

Document generation scripts are in scripts. They use local packages in .project_tools; they are documentation utilities, not the subsidence prediction engine.
