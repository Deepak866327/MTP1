# Subsidence prediction project

This workspace contains the source material and rebuild plan for a surface subsidence and strain prediction project using the Influence Function Method for flat and gently inclined coal seams.

Phase 1 is implemented: validated project JSON files, seam geometry, independent extraction and surface meshes, and a portable geometry preview. The displacement and strain solvers are scheduled for later phases.

The implementation uses Python 3.11+ and pinned NumPy. From this directory in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip --use-feature=truststore install -r requirements.txt
.\.venv\Scripts\python.exe -m subsidence validate examples/adriyala_geometry.json
.\.venv\Scripts\python.exe -m subsidence mesh examples/synthetic_flat.json --output outputs/flat_run
.\.venv\Scripts\python.exe -m subsidence mesh examples/adriyala_geometry.json --output outputs/adriyala_run
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Open `preview.svg` in each output directory. Each bundle also contains the saved project, summary, source and surface CSVs, and coordinate/area arrays in `geometry.npz`. Output directories must be new or empty. Source spacing and surface spacing are separate inputs. Overlapping extraction rectangles contribute their union once; partially intersected cells use exact clipped rectangular fragments.

The synthetic example contains 800 sources and 2,000 surface points. The Adriyala example contains 5,775 sources and 10,857 surface points, reconstructed from reported geometry. These are geometry checks; the published field errors have not been reproduced.

- [Phase 1 implementation, conventions, and acceptance results](docs/PHASE1_IMPLEMENTATION.md)
- [Synthetic flat-panel project](examples/synthetic_flat.json)
- [Reported Adriyala geometry project](examples/adriyala_geometry.json)

The original project and the complete rebuild plan are described in:

- [Project understanding and phase-by-phase plan — Word](docs/Subsidence_Project_Understanding_and_Rebuild_Plan.docx)
- [Project understanding and phase-by-phase plan — PDF](docs/Subsidence_Project_Understanding_and_Rebuild_Plan.pdf)
- [Editable plan — Markdown](docs/PROJECT_UNDERSTANDING_AND_REBUILD_PLAN.md)
- [Durable project memory](PROJECT_MEMORY.md)
- [Reported Adriyala inputs, with unresolved conventions](docs/adriyala_reported_inputs.json)

The plan and its Word/PDF copies are the 3 November planning documents. The Phase 1 implementation note and project memory record the current implementation status. The main plan includes the original model and software features, equations, case-study parameters, reported validation results, reproduction gaps, modest improvements, suggested architecture, and nine implementation phases with acceptance criteria.

Source OCR and upright page images are in docs/source_extracts. OCR is imperfect; precise equations and values should be checked against the images and original PDFs.

Document generation scripts are in scripts. They use local packages in .project_tools; they are documentation utilities, not the subsidence prediction engine.
