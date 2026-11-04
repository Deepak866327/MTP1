# Phase 1 implementation

Implemented 4 November 2026 against Phase 1 of the rebuild plan. This phase supplies validated geometry and independent meshes. Prediction, strain, calibration, field comparison, and the interactive application remain for later phases.

## Run the implementation

Use Python 3.11 or newer. The runtime dependency is pinned to NumPy 2.4.6; tests use Python's standard `unittest` package. Existing documentation/OCR utilities in `.project_tools` are separate from this environment.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip --use-feature=truststore install -r requirements.txt
.\.venv\Scripts\python.exe -m subsidence validate examples/adriyala_geometry.json
.\.venv\Scripts\python.exe -m subsidence mesh examples/synthetic_flat.json --output outputs/flat_run
.\.venv\Scripts\python.exe -m subsidence mesh examples/adriyala_geometry.json --output outputs/adriyala_run
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

During setup on this workstation, pip 24 needed the Windows system certificate store. The successful install used `-m pip --use-feature=truststore install -r requirements.txt`. Certificate verification remained enabled.

`validate` checks the schema and physical geometry without creating meshes. `mesh` applies mesh size limits and writes artifacts. Errors return exit code 2 with a readable message. Choose a new or empty output directory for every export; existing artifacts are protected. The geometry preview is a standalone SVG that opens in a browser without a server.

## Project format and validation

The examples are complete loadable version-1 JSON files. Top-level fields are:

| Field | Meaning |
| --- | --- |
| `schema_version` | Integer `1` |
| `name` | Nonempty descriptive name |
| `evidence` | `synthetic_geometry`, `reported_geometry`, or `custom_geometry` |
| `units` | Exactly `{"length": "m"}` |
| `surface_elevation_m` | Elevation of the horizontal observation surface |
| `field` | Observation rectangle: `xmin_m`, `xmax_m`, `ymin_m`, `ymax_m` |
| `seam` | `reference_xyz_m` and `normal_xyz`, each three numbers |
| `extraction_rectangles` | Rectangles in horizontal plan coordinates; empty list is valid |
| `source_mesh` | Positive `dx_m`, `dy_m` for extraction discretization |
| `surface_grid` | Independent positive `dx_m`, `dy_m` for observation cells |
| `provenance` | Optional JSON metadata, retained on save |
| `notes` | Optional list of strings, retained on save |

Unknown schema fields, duplicate JSON keys, unsupported versions/units, nonfinite numbers, numeric strings, booleans as coordinates, reversed/zero extents, and nonpositive spacing are rejected. Solver parameters are deliberately absent from the schema. The Adriyala transcription's p and beta remain in provenance as reported values that are not applied.

Coordinates are global Cartesian coordinates in metres, with z positive upward. Rectangle coordinates are horizontal projections. The observation field can be smaller or larger than the extraction footprint: sources outside the observation field remain included. Changing the display/evaluation domain therefore cannot crop extraction.

The seam normal is normalized and oriented upward. The original input vector is retained in saved projects; the normalized vector is also exported in the summary. The plane is:

```text
z(x,y) = z_ref - (n_x*(x-x_ref) + n_y*(y-y_ref)) / n_z
vertical_depth = surface_elevation - z
```

A zero normal and a normalized `abs(n_z) < 1e-12` are rejected. The reference point and every extraction-rectangle corner must lie strictly below the surface. Corner checks establish the depth condition over the entire planar footprint. Geometry with dip above 12 degrees can be inspected, but the summary flags that it exceeds the report's prediction scope.

## Extraction and surface discretization

The extraction mesh uses the union of all rectangles. An x-sweep merges active y intervals into disjoint rectangular tiles. Tiles are intersected with a regular plan grid anchored at the extraction bounding box's minimum x/y. Every resulting fragment contributes one source at its rectangle midpoint, placed on the seam plane. Duplicate, nested, touching, overlapping, disconnected, and empty regions are handled.

Fragments have exact geometric plan area, up to floating-point rounding. Boundary fragments may be smaller than nominal spacing, and one nominal grid cell may yield several fragments. A disconnected extracted shape is never represented by a centroid in its unmined gap. Region boundaries can create extra fragments even when the geometric union is unchanged. Total union area is preserved; future quadrature convergence must still be tested.

Both area arrays are explicit:

```text
plan_area = fragment_width * fragment_height
seam_area = plan_area / upward_unit_normal_z
```

Providing both measures does not choose the inclined solver's integration convention. Vertical depth is exported as a geometric quantity; the later solver must still specify vertical versus normal separation.

The surface grid is cell centered and anchored at the field's minimum x/y. If an extent is not divisible by spacing, its last cell is shortened and its point is at the shortened cell's midpoint. This preserves the requested extent. Exact-divisor cases reproduce the report's `i*dx + dx/2` coordinates. The source and observation grids can be refined independently.

Each mesh is limited to 2,000,000 cells/points by default, with axis limits checked before allocation. The Python builders accept a `max_cells` override. Mesh arrays use float64. Plane residual checks use metre-scale absolute tolerances of `1e-12` in the examples; random union-area comparisons use 12 decimal places on small synthetic geometries. These are numerical verification tolerances, not field-accuracy guarantees.

## Exported artifacts and Python access

| File | Contents |
| --- | --- |
| `project.json` | Reloadable project, with reported inputs/provenance preserved |
| `summary.json` | Counts, units, shape/order, dip/normal, areas, depth ranges, plane residual, evidence and notes |
| `geometry.npz` | Numeric arrays loadable with `allow_pickle=False` |
| `sources.csv` | IDs, xyz, both areas, vertical depths, fragment bounds |
| `surface.csv` | `row_y`, `col_x`, xyz |
| `preview.svg` | Equal-scale plan view and a section along dip (x for a flat seam); points sampled for display |

The section's horizontal and vertical scales differ and are labeled accordingly. Full arrays and CSVs retain every point. Surface arrays have shape `(ny, nx, 3)`: x varies fastest when flattened in C order. Source coordinates have shape `(n_sources, 3)`. Source bounds have columns `xmin, xmax, ymin, ymax`. NPZ area and depth array names include units.

```python
import numpy as np
from subsidence import load_project, build_source_mesh, build_surface_grid

project = load_project("examples/adriyala_geometry.json")
sources = build_source_mesh(project)
surface = build_surface_grid(project)
print(sources.xyz_m.shape, surface.xyz_m.shape)

with np.load("outputs/adriyala_run/geometry.npz", allow_pickle=False) as arrays:
    xyz = arrays["source_xyz_m"]
    plan_area = arrays["source_plan_area_m2"]
    observation_xyz = arrays["surface_xyz_m"]
```

## Acceptance results

All 25 automated tests passed on Python 3.11.9 with NumPy 2.4.6 on this workstation. Both example bundles were generated, reopened, and their previews inspected. Editable package installation was also verified. The tests include an independent rectangle-union area oracle over 30 seeded random configurations, corner depth checks, non-overlap, normal scaling/sign, partial boundary areas/centers, independent mesh changes, empty extraction, schema rejection, export round trips, and command-line execution.

| Quantity independently computed in Phase 1 | Synthetic flat panel | Adriyala reported geometry |
| --- | --- | --- |
| Source spacing, x/y | 10 / 10 m | 10 / 10 m |
| Surface spacing, x/y | 20 / 20 m | 10 / 10 m |
| Source fragments | 800 | 5,775 |
| Surface shape, y/x | 40 × 50 | 47 × 231 |
| Surface points | 2,000 | 10,857 |
| Union plan area | 80,000 m² | 577,500 m² |
| Mesh plan-area error | 0 m² | 0 m² |
| Dip | 0° | 10.30467587° |
| Extraction-corner vertical depth range | 400–400 m | 367.79912990–456.68 m |
| Maximum source plane residual | 0 m | approximately 4.9e-14 m |

Adriyala geometry comes from the existing source transcription of MTP PDF pp.24–25. The 10 m source spacing is an explicit rebuild discretization choice; the report's 10 m surface grid is retained independently. The physical panel length (2,333 m) and physical minimum depth (366.12 m) remain distinct from the computational length (2,310 m) and plane-derived minimum depth. Nothing is adjusted to force agreement.

These checks satisfy the Phase 1 geometry/mesh acceptance criteria. They do not reproduce the reported subsidence maps or RMSE. Original source code and raw monitoring data remain unavailable. Before Phase 4, resolve the inclined transformation, depth and area conventions, p/Smax normalization, and kernel support. Phase 2 can proceed with the flat-seam solver and independent analytical integral verification.
