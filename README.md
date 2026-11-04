# Subsidence prediction project

This workspace contains the source material and rebuild plan for a surface subsidence and strain prediction project using the Influence Function Method for flat and gently inclined coal seams.

Phases 1 and 2 are implemented: validated project geometry, independent meshes, and a flat-seam solver for Ux, Uy and Uz with analytical verification. Strain and inclined-seam prediction are scheduled for later phases.

The implementation uses Python 3.11+ with pinned NumPy and Matplotlib. From this directory in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip --use-feature=truststore install -r requirements.txt
.\.venv\Scripts\python.exe -m subsidence validate examples/adriyala_geometry.json
.\.venv\Scripts\python.exe -m subsidence mesh examples/synthetic_flat.json --output outputs/flat_run
.\.venv\Scripts\python.exe -m subsidence mesh examples/adriyala_geometry.json --output outputs/adriyala_run
.\.venv\Scripts\python.exe -m subsidence solve-flat examples/synthetic_flat.json --model examples/flat_model.json --output outputs/flat_prediction
.\.venv\Scripts\python.exe -m subsidence verify-flat --output outputs/flat_verification
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Open `preview.svg` in each output directory. Each bundle also contains the saved project, summary, source and surface CSVs, and coordinate/area arrays in `geometry.npz`. Output directories must be new or empty. Source spacing and surface spacing are separate inputs. Overlapping extraction rectangles contribute their union once; partially intersected cells use exact clipped rectangular fragments.

The synthetic example contains 800 sources and 2,000 surface points. The Adriyala example contains 5,775 sources and 10,857 surface points, reconstructed from reported geometry. These are geometry checks; the published field errors have not been reproduced.

`solve-flat` adds displacement arrays, CSV, sign/unit metadata, and `displacement_maps.png`/`.svg` to the geometry bundle. Model settings live in a separate JSON file; the synthetic example uses Smax=1 m, beta=20 degrees and full Gaussian support. The Adriyala seam is inclined and is rejected by this solver. The Python API also predicts at exact supplied surface coordinates.

`verify-flat` writes an analytical comparison, convergence tables and plots. All 50 tests pass, including the 25 Phase 1 checks. On the fixed synthetic benchmark, maximum component error decreases from 0.00873849 m at 40 m source spacing to 0.0000340824 m at 2.5 m spacing. This verifies numerical integration, not field accuracy. Run convergence checks for other configurations before calibration.

- [Phase 1 implementation, conventions, and acceptance results](docs/PHASE1_IMPLEMENTATION.md)
- [Phase 2 equations, usage, and verification results](docs/PHASE2_IMPLEMENTATION.md)
- [Synthetic flat-panel project](examples/synthetic_flat.json)
- [Synthetic flat-model settings](examples/flat_model.json)
- [Reported Adriyala geometry project](examples/adriyala_geometry.json)

The original project and the complete rebuild plan are described in:

- [Project understanding and phase-by-phase plan — Word](docs/Subsidence_Project_Understanding_and_Rebuild_Plan.docx)
- [Project understanding and phase-by-phase plan — PDF](docs/Subsidence_Project_Understanding_and_Rebuild_Plan.pdf)
- [Editable plan — Markdown](docs/PROJECT_UNDERSTANDING_AND_REBUILD_PLAN.md)
- [Durable project memory](PROJECT_MEMORY.md)
- [Reported Adriyala inputs, with unresolved conventions](docs/adriyala_reported_inputs.json)

The plan and its Word/PDF copies are the 3 November planning documents. The Phase 1/2 implementation notes and project memory record the current implementation status. The main plan includes the original model and software features, equations, case-study parameters, reported validation results, reproduction gaps, modest improvements, suggested architecture, and nine implementation phases with acceptance criteria.

Source OCR and upright page images are in docs/source_extracts. OCR is imperfect; precise equations and values should be checked against the images and original PDFs.

Document generation scripts are in scripts. They use local packages in .project_tools; they are documentation utilities, not the subsidence prediction engine.
