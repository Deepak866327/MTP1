# Subsidence prediction project

This workspace contains the source material and rebuild plan for a surface subsidence and strain prediction project using the Influence Function Method for flat and gently inclined coal seams.

Phases 1–3 are implemented: validated geometry, independent meshes, flat-seam Ux/Uy/Uz, global horizontal strains Ex/Ey, and custom line profiles with numerical verification. Inclined-seam prediction is the next phase.

The implementation uses Python 3.11+ with pinned NumPy and Matplotlib. From this directory in PowerShell:

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
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Open `preview.svg` in each output directory. Each bundle also contains the saved project, summary, source and surface CSVs, and coordinate/area arrays in `geometry.npz`. Output directories must be new or empty. Source spacing and surface spacing are separate inputs. Overlapping extraction rectangles contribute their union once; partially intersected cells use exact clipped rectangular fragments.

The synthetic example contains 800 sources and 2,000 surface points. The Adriyala example contains 5,775 sources and 10,857 surface points, reconstructed from reported geometry. These are geometry checks; the published field errors have not been reproduced.

`solve-flat` adds displacement arrays, CSV, sign/unit metadata, and `displacement_maps.png`/`.svg` to the geometry bundle. Model settings live in a separate JSON file; the synthetic example uses Smax=1 m, beta=20 degrees and full Gaussian support. The Adriyala seam is inclined and is rejected by this solver. The Python API also predicts at exact supplied surface coordinates.

`verify-flat` writes an analytical comparison, convergence tables and plots. On the fixed synthetic benchmark, maximum component error decreases from 0.00873849 m at 40 m source spacing to 0.0000340824 m at 2.5 m spacing. This verifies numerical integration, not field accuracy. Run convergence checks for other configurations before calibration.

`deform-flat` adds strain maps, arrays and CSVs, plus profiles when `--profiles` is supplied. Derivatives use actual cell-center spacing and second-order one-sided boundaries, flagged in exports; at least three centers per axis are required. Ex/Ey are dimensionless, displayed in mm/m (multiply by 1000); positive means tensile. Profiles include distance, Ux/Uy/Uz and global Ex/Ey, including on oblique lines. Endpoints must be within the cell-center domain; extrapolation is disabled.

`sample-profiles` reuses saved Phase 2 or Phase 3 displacement arrays and derives strain without rerunning the influence solver. Edit `examples/profiles.json` or use a copy to change lines. Keep the source run with these profile exports. `verify-deformation` checks manufactured derivatives, interpolation, direct-solver comparisons, and independent analytical strain convergence. All **76 tests** pass, retaining the previous 50 checks. The Phase 3 benchmark reaches 0.00170846 mm/m derivative error at 5 m observation spacing; this is a synthetic numerical check.

- [Phase 1 implementation, conventions, and acceptance results](docs/PHASE1_IMPLEMENTATION.md)
- [Phase 2 equations, usage, and verification results](docs/PHASE2_IMPLEMENTATION.md)
- [Phase 3 strain, profiles, and verification results](docs/PHASE3_IMPLEMENTATION.md)
- [Synthetic flat-panel project](examples/synthetic_flat.json)
- [Synthetic flat-model settings](examples/flat_model.json)
- [Example profile definitions](examples/profiles.json)
- [Reported Adriyala geometry project](examples/adriyala_geometry.json)

The original project and the complete rebuild plan are described in:

- [Project understanding and phase-by-phase plan — Word](docs/Subsidence_Project_Understanding_and_Rebuild_Plan.docx)
- [Project understanding and phase-by-phase plan — PDF](docs/Subsidence_Project_Understanding_and_Rebuild_Plan.pdf)
- [Editable plan — Markdown](docs/PROJECT_UNDERSTANDING_AND_REBUILD_PLAN.md)
- [Durable project memory](PROJECT_MEMORY.md)
- [Reported Adriyala inputs, with unresolved conventions](docs/adriyala_reported_inputs.json)

The plan and its Word/PDF copies are the 3 November planning documents. The Phase 1–3 implementation notes and project memory record the current implementation status. The main plan includes the original model and software features, equations, case-study parameters, reported validation results, reproduction gaps, modest improvements, suggested architecture, and nine implementation phases with acceptance criteria.

Source OCR and upright page images are in docs/source_extracts. OCR is imperfect; precise equations and values should be checked against the images and original PDFs.

Document generation scripts are in scripts. They use local packages in .project_tools; they are documentation utilities, not the subsidence prediction engine.
