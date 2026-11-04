# Phase 3: horizontal strain and custom profiles

Implemented 4 November 2026 against Phase 3 of the rebuild plan. This adds Ex/Ey derivatives, arbitrary line sampling of all five global fields, plots, tables and reproducible numerical verification. It uses the existing flat-seam displacement engine. Inclined geometry remains a Phase 4 solver task.

Phase 1 is the `cf1860d` baseline; Phase 2 follows as `5adc9eb`. Phase 3 is recorded in a separate subsequent commit on `main`. Publishing Phase 3 includes the previously local Phase 2 commit.

## Run

The environment remains Python 3.11+ with NumPy 2.4.6 and Matplotlib 3.10.8. No new dependencies were added. From the workspace in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m subsidence deform-flat examples/synthetic_flat.json --model examples/flat_model.json --profiles examples/profiles.json --output outputs/flat_deformation
.\.venv\Scripts\python.exe -m subsidence sample-profiles outputs/flat_deformation --profiles examples/profiles.json --output outputs/new_profiles
.\.venv\Scripts\python.exe -m subsidence verify-deformation --output outputs/deformation_verification
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Choose a new or empty directory for each export. Omit `--profiles` from `deform-flat` to export only displacement and strain. `sample-profiles` accepts a saved `solve-flat` or `deform-flat` output folder; it reads the numerical arrays and recomputes their inexpensive derivatives without calling the influence solver. Changing line definitions therefore does not require a new full displacement calculation. Retain the source run with standalone profile exports.

Generated local examples are `outputs/phase3_flat`, `outputs/phase3_verification`, and `outputs/phase3_profiles_from_saved_run`. The last example successfully samples the earlier Phase 2 bundle at `outputs/phase2_flat`.

## Derivatives, axes, boundaries and units

MTP PDF p.22, Eq.12a–12b, was visually checked against its scanned image. It reports centered differences for Ex and Ey. The rebuild's documented storage order is `(ny,nx,3)`, so:

```text
Ex = dUx/dx  (array axis 1)
Ey = dUy/dy  (array axis 0)

Uniform-grid interior:
Ex[j,i] = (Ux[j,i+1] - Ux[j,i-1]) / (2*dx)
Ey[j,i] = (Uy[j+1,i] - Uy[j-1,i]) / (2*dy)
```

`horizontal_strain(surface, displacement_m)` uses three-point, second-order differences. It takes the actual x/y cell-center coordinates rather than assuming nominal spacing. Interior derivatives reduce to the equations above on a uniform grid. Where the final cell is shortened, the nonuniform formula differentiates the quadratic interpolant through the three centers.

At the first/last x centers, Ex uses a second-order one-sided stencil; Ey does so at the first/last y centers. On a uniform axis, the starting stencil is `(-3*f0+4*f1-f2)/(2*h)`. Nonuniform boundaries use the corresponding three-point quadratic formula. Boundary treatment is an explicit rebuild choice because the report does not specify its edge implementation.

At least three cell centers are required on each axis. A thinner grid is rejected with a readable error. Rectilinear monotonic axes, consistent cell edges/centers, horizontal surface, finite numeric displacements and matching shapes are checked. Mesh/source refinement remains independent of these observation-grid derivatives.

`boundary_mask` marks the outer row/column, the union of cells where either strain uses a one-sided stencil. Ex uses one-sided x stencils only at x edges, and Ey uses one-sided y stencils only at y edges. Exports provide both all-cell and interior-only statistics so boundary treatment remains visible.

Strain is dimensionless (m/m). Positive strain is tensile; negative is compressive. Display/export conversion is:

```text
strain_mm_per_m = 1000 * strain
0.001 dimensionless = 1 mm/m
```

The maps use signed color scales centered at zero. Ex and Ey share the same magnitude scale. Displacement signs remain unchanged from Phase 2: global z is upward, so downward settlement has negative Uz.

## Line profiles

Profile definitions have their own strict version-1 JSON format, illustrated by `examples/profiles.json`:

```json
{
  "schema_version": 1,
  "units": {"length": "m"},
  "profiles": [
    {
      "name": "Oblique line",
      "start_xy_m": [-350.0, -250.0],
      "end_xy_m": [350.0, 250.0],
      "sample_count": 173
    }
  ]
}
```

Names must be nonempty and unique. Endpoints must be finite, distinct 2D coordinates in metres; sample counts must be integers from 2 to 1,000,000. Unknown fields, unsupported units/version, duplicate JSON keys, nonfinite values and booleans in numeric fields are rejected. The three example lines pass through the panel center along x, along y, and obliquely.

Sampling uses bilinear interpolation on actual cell centers, including nonuniform edge spacing. Endpoints are included and distance starts at zero and ends at the line's horizontal length. Start/end order determines the profile direction; reversing the line reverses the samples but does not change the global field signs.

**The interpolation domain is the rectangle bounded by the outermost cell centers.** It is smaller than the physical observation field. The synthetic 20 m grid has physical bounds x=[-500,500], y=[-400,400], but valid profile bounds x=[-490,490], y=[-390,390]. An endpoint outside those center bounds is rejected; values are never extrapolated or silently clipped. Direct Phase 2 solver evaluation remains available at arbitrary surface coordinates.

Each profile contains distance, xyz, Ux/Uy/Uz, Ex/Ey, mm/m conversions, and `boundary_influenced`. The flag is true if a nonzero interpolation weight uses a boundary-mask cell. A zero-weight boundary neighbor does not affect the flag. Hollow markers identify affected samples in strain plots.

Ex and Ey remain **global x/y normal components**, including along oblique lines. They are not strain projected along the line. Shear, principal strain and arbitrary directional strain are outside Phase 3. No shear quantity is inferred from Ex/Ey alone.

A displacement fingerprint prevents pairing strains with a different displacement array. Grid-coordinate matching is also checked. Saved-run reading uses `allow_pickle=False`, checks shape/coordinates/field consistency, and compares saved model/project metadata. Early Phase 2 example bundles lacking an embedded project remain readable through their standalone project, saved grid, and model settings.

## Python interface

```python
from subsidence import (
    load_project, load_flat_model, build_surface_grid, solve_flat,
    horizontal_strain, ProfileLine, sample_profile,
)

project = load_project("examples/synthetic_flat.json")
model = load_flat_model("examples/flat_model.json")
surface = build_surface_grid(project)
displacement = solve_flat(project, model, surface.xyz_m)
strain = horizontal_strain(surface, displacement.displacement_m)

line = ProfileLine("Custom line", (-350, -250), (350, 250), 173)
profile = sample_profile(surface, displacement.displacement_m, strain, line)
print(strain.ex.shape, profile.distance_m.shape)
```

`StrainResult.ex` and `.ey` have shape `(ny,nx)`; `.ex_mm_per_m` and `.ey_mm_per_m` provide the display conversion. `ProfileResult.displacement_m` has shape `(n,3)`; its distance, strains and boundary flags each have length n. `load_profiles`/`save_profiles` preserve the line settings.

## Artifacts

A `deform-flat` bundle retains all Phase 1/2 artifacts and adds:

| File | Contents |
| --- | --- |
| `strain.npz` | xyz, Ex/Ey, mm/m conversions and boolean boundary mask |
| `strain.csv` | Grid indices, coordinates, dimensionless/mm/m strains and boundary flag |
| `strain_summary.json` | Derivative method, axis/units/signs, boundary policy/count, fingerprint, all/interior statistics |
| `strain_maps.png` / `.svg` | Signed global strain maps in mm/m |
| `profiles/profiles.json` | Saved line definitions, when profiles are requested |
| `profiles/profile_summary.json` | Sampling conventions, source grid context and line-to-file mapping |
| `profiles/profile_NNN.csv` / `.npz` | Sampled five fields, distance, coordinates, units and flags |
| `profiles/profile_NNN.png` / `.svg` | Displacement and global-strain curves against distance |

Profile filenames use sequential numbers; user names are labels and never become paths. Standalone `sample-profiles` creates the same profile artifacts plus project/model snapshots. Its summary identifies the source run. The profile bundle uses the retained source displacement grid for reproduction.

## Verification and limitations

All **76 automated tests** pass: 25 Phase 1, 25 Phase 2 and 26 Phase 3 tests. The **9 Phase 3 acceptance checks** also pass. The generated strain maps, oblique profile and derivative-convergence plot were visually inspected.

Manufactured checks cover constant, affine, bilinear and quadratic displacement fields with known derivatives. They verify axis selection, cross terms, nonuniform spacing, one-sided boundaries and interpolation against known values. Affine strain errors are approximately `3.3e-16`; the declared tolerance is `1e-12` dimensionless. Bilinear displacement/profile errors use `1e-12 m`; bilinear strain profiles use `1e-12` dimensionless. These checks do not depend on subsidence solver output.

An independent analytical Ex/Ey reference differentiates the closed-form Gaussian first moments rather than using finite differences. For t measured from observation to source, `g(t)=exp(-pi*t²/R²)/R`, `I0=integral g(t)dt`, and `J=integral t*g(t)dt`:

```text
dJ/dP = a*g(a) - b*g(b)
Ex = Smax/H * (a_x*g(a_x)-b_x*g(b_x)) * I0_y
Ey = Smax/H * I0_x * (a_y*g(a_y)-b_y*g(b_y))
```

The tests additionally compare this reference with independently written Gauss-Legendre integration of the differentiated kernel for several coordinates. Observation-grid refinement uses analytical displacement values, isolating derivative error from source quadrature:

| Observation spacing (m) | Grid points | Maximum Ex/Ey error, including boundaries (dimensionless) |
| --- | --- | --- |
| 40 | 500 | 9.92474440e-5 |
| 20 | 2,000 | 2.60180981e-5 |
| 10 | 8,000 | 6.78558928e-6 |
| 5 | 32,000 | 1.70846288e-6 |

The finest result is **0.00170846 mm/m**, below the predefined `2e-6` dimensionless tolerance. The trend is approximately second order. These numbers apply to the specified 400-by-200 m flat panel, H=400 m, Smax=1 m and beta=20 degrees; other meshes and parameter choices require convergence checks.

On the 20 m observation grid, an 81-point synthetic oblique profile differs from direct solver displacement by at most **0.00544022 m** (fixed tolerance 0.01 m). Its sampled strains differ by at most **3.37171666e-5 dimensionless**, or **0.0337172 mm/m**, from central differences of direct solver values using a 0.25 m offset (fixed tolerance 5e-5 dimensionless). These differences include interpolation and derivative approximation. Sampling more line points does not refine the underlying grid; reduce observation spacing to assess that error.

Boundary information is exported and remains relevant even where the manufactured examples happen to be exact. Neither synthetic checks nor analytically verified gradients establish measured mine-strain accuracy. Adriyala RMSE remains source-reported; no field result or accuracy improvement is claimed. Phase 4 must resolve inclined transformations and conventions before inclined prediction can run.
