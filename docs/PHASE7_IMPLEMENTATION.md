# Phase 7: local desktop application and reproducible runs

Implemented 5 November 2026, package version 0.7.0. Phase 7 adds a native Tkinter/Matplotlib application over the existing flat/inclined prediction, strain, profile, observation and calibration core. No web server, hosted service or new third-party dependency is required. Use the source checkout with Python 3.11+ and Tk support (included with the standard Windows Python installer).

The interface is implemented and verified on Windows/Tk 8.6. The underlying inclined formulation remains the explicit Phase 4 reconstruction. Adriyala station coordinates/measurements and original-engine convention gaps remain unresolved; opening reported geometry does not establish field validation.

## Start locally

From the repository directory in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip --use-feature=truststore install -r requirements.txt
.\.venv\Scripts\python.exe -m subsidence gui
```

If this is a fresh checkout, first create `.venv` using `python -m venv .venv`. Built-in geometry examples are read from this checkout's `examples` folder. The scientific core and archives can be used without a graphical display; the GUI requires a local graphical desktop and Tk. No browser is used.

Optionally open a previously saved desktop project at startup:

```powershell
.\.venv\Scripts\python.exe -m subsidence gui --project path/to/desktop_project.json
```

After `pip install -e .`, `subsidence-gui` is also available in the environment's Scripts directory.

## Prediction and inspection workflow

1. Choose **Synthetic flat** or **Synthetic inclined** and click **Load example**. **Adriyala reported geometry** loads the reported inputs with their reconstruction caveats.
2. Edit the left-side forms for project/evidence/source, Smax or p in metres, beta in degrees, surface elevation, field bounds, seam reference and normal, source spacing and surface spacing. Scroll the left panel to reach extraction rectangles and notes. Select an extraction row to load its coordinates; **Add**, **Replace** and **Remove** edit the rectangular union.
3. Click **Compute displacement + strain**. Work runs in a background thread with progress/status feedback; controls are restored on success or failure. At least three cell centers per surface axis are required for strain. Invalid geometry or profiles produce a readable error before solving when feasible.
4. In **Field map**, choose Ux, Uy, Uz, positive settlement, Ex or Ey. The map uses actual cell edges and global metre coordinates. Hover to read the containing cell's center, value/unit and one-sided strain boundary flag. Minimum, maximum and mean refer to displayed grid samples, not a continuous peak search.
5. Ex/Ey are displayed in mm/m (1000 times dimensionless strain), with tensile positive. Their diverging color scale is symmetric about zero; selecting a sequential palette switches the strain display to RdBu_r. Pan, zoom, reset and image saving use the Matplotlib toolbar.
6. In **Profiles**, select a supplied line or enter its name, global x1/y1/x2/y2 endpoints and sample count, then **Add / replace line**. Reusing a name replaces that line. Endpoints must lie inside the actual cell-center domain; no extrapolation is performed. Choose any of the six fields. Ex/Ey stay global normal components on oblique lines; samples influenced by one-sided boundaries are marked.

Changing field, palette or profile samples reuses cached arrays. The influence solver is called only for explicit compute/calibrate actions. Edited physical inputs leave the previous run visible with a status message; exporting with changed geometry, model or observations is blocked until recomputation. Results keep their computed project labels. Profiles are validated against the selected grid before computation/export.

## Observations and calibration

**Observations → Load station CSV + metadata** accepts the Phase 5 station format and strict metadata. Supply station IDs, predefined fit/test line roles, global x/y, observed Uz, units, sign/datum, coordinate reference, stage and provenance. Optional line distances are used as the profile abscissa; otherwise station IDs remain in original CSV order. No survey transform is invented. Uploading or clearing observations clears the previous comparison display and requires compute/calibrate to refresh its numbers.

After computation, the tab displays observed/predicted profiles, signed residuals and RMSE/MAE/bias by line. Displayed observations use canonical global Uz; positive-settlement inputs are converted only according to their metadata. Synthetic and surveyed-digitized evidence remains labeled.

To try calibration without field data:

1. Choose **Synthetic calibration demo → Load example**. This loads independent-reference synthetic observations, a manual comparison model and explicit demonstration bounds/starts. It does not load mine measurements.
2. Open **Calibration → Fit settings**. Review amplitude/angle bounds, bounds basis, initial guesses (one `amplitude, beta` pair per line), evaluation limit and justification. **Load fit settings** imports a strict Phase 6 settings JSON; imported stopping tolerances are retained. At least two distinct interior starts are required.
3. Click **Calibrate fit line + frozen test**. Only `fit` stations enter optimization. Bounds with a synthetic basis are rejected for nonsynthetic observations. Actual site bounds must be justified independently of test outcomes.
4. The chosen fitted parameters populate the left forms, maps are computed once for that frozen model, and station comparisons reuse the calibration's frozen station evaluation. The **Results** subtab shows manual/fitted parameters, fit and held-out errors, selected start/SSE and identifiability warnings. Raw numerical diagnostics remain available in **Run details**.
5. Export the run ZIP to retain all original manual parameters, starts/objectives, residuals, source bytes/hashes, plots and held-out reports. All-failed calibration attempts show diagnostics and select no new fitted run; a previously displayed run remains the earlier result.

The supplied manual model is the comparison baseline for that calibration action. It is not automatically the report's original engine. Repeated use of testing outcomes to choose bounds/preprocessing/model revisions requires new independent evaluation data. No confidence interval or universal accuracy improvement is inferred.

## Save, reopen and export

| Action | What it preserves/opens |
| --- | --- |
| **Save project** | Self-contained desktop JSON with geometry/model, provenance/notes, profile definitions, display field/palette, fit settings and exact uploaded CSV/metadata bytes (base64 encoded). It saves current forms, without numerical arrays. |
| **Open project** | Desktop project JSON, or a standard geometry JSON followed by a model-file selection. Recompute after opening settings. |
| **Export run ZIP** | Complete computed run: desktop project, ordinary CLI-compatible grid project/model JSON, displacement/strain/profile CSV/NPZ, PNG/SVG figures, units/signs/statistics, optional station and calibration bundles, README and SHA-256 manifest. Uses a new filename. |
| **Open run ZIP** | Restores settings, evidence, numeric arrays, profiles, observations and calibration details. No influence/station solver is called. Strain/metrics are checked against saved numeric data. |
| **Open grid folder** | Opens prior CLI `solve-*`/`deform-*` output folders using the existing saved-grid reader. Saved profile definitions are restored when present. It cannot recover observations/calibration that were never saved in that folder. |
| Plot toolbar save | Saves that figure only. Use Export run ZIP for a complete project/run. |

Run reopening checks archive paths, duplicate entries, file hashes, document/grid model agreement, coordinate shapes, station/source consistency and saved strain versus displacement. Arrays use `allow_pickle=False`. Archive limits are 2,000 members and 512 MiB uncompressed; export reserves room for its manifest and refuses oversized runs. These integrity checks detect accidental changes, not authenticate scientific provenance. Existing run ZIPs are not overwritten.

Re-exporting an opened calibration run retains the original calibration folder bytes. New display/profile choices can be saved without solving. Fit settings associated with a completed calibration remain in the numerical run; **Save project** can separately preserve newly edited settings for a future calibration.

## Architecture and verification

- `workspace.py`: Tk-independent project documents, cached application runs, direct core computation/calibration, saved-run integrity and numeric restoration.
- `desktop_plots.py`: scientific map/profile/station figures with explicit coordinates, sign and display units.
- `desktop.py`: native forms, tabs, file dialogs, hover interaction and queued worker completion. Tk objects and figures are updated on the main thread. Cycle collection is deferred during worker operations and performed on the Tk thread so disposed Tk resources are not finalized by the numerical worker.
- `phase7_verification.py`: portable synthetic examples and acceptance evidence.
- `evaluation.summarize_stations`: shared residual/metric calculation for newly computed and restored station predictions; scientific metric definitions are unchanged.

Run the full suite and generate a review bundle:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m subsidence verify-desktop --output outputs/my_desktop_verification
```

The full suite passes **172 tests** (144 previous + 28 Phase 7). Eleven native GUI workflow tests run with a withdrawn Tk window on this Windows environment; they cover real callbacks/background jobs, prediction, calibration, failed fits, geometry/rectangle forms, observation upload/clearing, standard/desktop project import, project saving and run export/open. Seventeen workspace/plot/CLI tests cover numerical parity, cache reuse, exact archive restoration, preservation of calibration assets, stale-input checks, signed scales, hover coordinates, invalid inputs and archive integrity/path/size checks. Native GUI tests require Tk/display support; pure workspace verification can run without a display.

`verify-desktop` passes **14 synthetic bundle checks**. It produces `flat_project.json`, `flat_run.zip`, `calibrated_project.json`, `calibrated_run.zip`, a signed strain figure and `verification.md/json`. Open the ZIPs directly in the application. These are constructed cases, not mine validation. Native window screenshots were separately inspected in the local `outputs/phase7_verification` directory.

## Remaining work

Phase 8 remains the wider convergence/domain/sensitivity and runtime/memory studies, final documentation/report and demonstration packaging. Real Adriyala fitting/held-out validation still requires located raw measurements, metadata, justified bounds and resolution of original-model ambiguities. This phase implements the application workflow without changing the scientific claims of earlier phases.
