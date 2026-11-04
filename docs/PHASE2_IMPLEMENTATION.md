# Phase 2: flat-seam displacement

Implemented 4 November 2026 against Phase 2 of the rebuild plan. The numerical core now calculates Ux, Uy, and Uz for a horizontal seam and a horizontal observation surface. This is a fresh Python implementation of the documented influence-function method with explicit conventions and independent analytical checks.

Phase 1 was committed and pushed first to `https://github.com/Deepak866327/MTP1.git`, branch `main`, commit `cf1860d87bbd1e94eac2be9ff265749cc015148a`. Phase 2 work follows that baseline. The original field results have not been reproduced.

## Run the example and verification

From the workspace in PowerShell, using Python 3.11+:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip --use-feature=truststore install -r requirements.txt
.\.venv\Scripts\python.exe -m subsidence solve-flat examples/synthetic_flat.json --model examples/flat_model.json --output outputs/flat_prediction
.\.venv\Scripts\python.exe -m subsidence verify-flat --output outputs/flat_verification
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The installed direct dependencies are NumPy 2.4.6 and Matplotlib 3.10.8. Matplotlib creates standalone PNG and SVG scientific figures; no graphical desktop or web server is required. Output directories must be new or empty. Previously generated outputs are preserved.

The geometry format remains version 1, so Phase 1 project files still load. Flat-model parameters live in a separate version-1 file:

```json
{
  "schema_version": 1,
  "model": "flat_stochastic_gaussian",
  "units": {"length": "m", "angle": "degrees"},
  "smax_m": 1.0,
  "influence_angle_deg": 20.0,
  "kernel_support": "full_gaussian"
}
```

Smax must be nonnegative. The influence angle must be strictly between 0 and 90 degrees. Settings reject unknown fields, unsupported units/models/support, nonfinite values and duplicate keys. Smax is a settlement amplitude in metres. The value 1 m here is a synthetic demonstration choice, not an Adriyala fit or a dimensionless subsidence factor.

## Implemented equations and source interpretation

The scanned source pages were visually checked again for this phase: MTP PDF p.15, Eq.1–3; textbook PDF p.18, Eq.12.24 and the influence-radius definition; textbook PDF p.20, Eq.12.32–12.35. The selected kernel and horizontal-to-vertical movement relationship are reported in those sources. The following signed global-coordinate implementation makes the rebuild conventions explicit:

```text
H = surface_elevation - seam_reference_z > 0
R = H * tan(influence_angle)
dx = source_x - observation_x
dy = source_y - observation_y
r = sqrt(dx^2 + dy^2)
Phi(r) = exp(-pi*r^2/R^2) / R^2
dS = Smax * Phi(r) * source_plan_area
dUx = dS * dx / H
dUy = dS * dy / H
dUz = -dS
U = sum of every extracted source-fragment contribution
```

Global z is upward; downward settlement has negative Uz. Positive settlement magnitude is `S=-Uz`. Each horizontal contribution points from the observation point toward its source. At a symmetric panel center, opposing horizontal contributions cancel. Ux, Uy, and Uz all have units of metres.

The support policy is the **full Gaussian**. R is the influence scale; sources farther than R still contribute. The kernel integrates to 1 over the full plane. Its integral inside radius R is only `1-exp(-pi)`, approximately 0.956786. No hard radius truncation, finite-ring adjustment or normalization over the mined portion is applied. This is an explicit rebuild choice, not a claim that the undocumented original engine used the same support policy.

Every source uses its clipped fragment's plan area. For a horizontal seam, plan area equals seam area and vertical depth equals normal separation. No inclined normalization or p-to-Smax conversion is needed or inferred here. The flat solver requires exactly zero horizontal normal components after normalization, so it rejects the reported Adriyala seam even for a zero-amplitude run.

## Solver and array interface

`subsidence/influence.py` contains the kernel and scale. `subsidence/solver.py` builds the source mesh and accumulates its contributions. It never allocates the complete observation-by-source matrix.

Default blocks contain up to 128 observations and 2,048 sources. Both chunk sizes can be changed through API keywords or CLI flags. Their product must not exceed 1,048,576 pairs. Pairwise working arrays are bounded by these blocks; source geometry and output arrays still require memory proportional to mesh sizes. Runtime remains proportional to the number of sources times the number of observations.

The Python API accepts arbitrary requested coordinates on the configured horizontal surface, including stations outside the observation field:

```python
from subsidence import load_project, load_flat_model, solve_flat

project = load_project("examples/synthetic_flat.json")
model = load_flat_model("examples/flat_model.json")

grid_result = solve_flat(project, model)
print(grid_result.displacement_m.shape)  # (40, 50, 3)

station_result = solve_flat(project, model, [[0, 0, 0], [200, 0, 0]])
print(station_result.ux_m, station_result.uy_m, station_result.uz_m)
```

Input and displacement arrays have the same shape `(...,3)`, with component order x/y/z or Ux/Uy/Uz. A default grid has shape `(ny,nx,3)`, with x varying fastest when flattened. Finite numeric coordinates are required, with z within `1e-9 m` of the configured surface. Empty extraction and zero amplitude return exact zeros. A zero-length station array returns a matching empty result. Changing the observation field or grid does not change predictions at fixed supplied coordinates.

## Independent analytical reference

`subsidence/reference.py` integrates the full Gaussian directly over rectangles. It never builds source cells or calls the numerical kernel. Overlapping extraction rectangles are first represented by their disjoint union tiles, whose integrals can be added.

For each coordinate axis, let `t=source_coordinate-observation_coordinate` and define:

```text
g(t) = exp(-pi*t^2/R^2) / R
I0(a,b) = integral[a,b] g(t) dt
         = 0.5 * (erf(sqrt(pi)*b/R) - erf(sqrt(pi)*a/R))
I1(a,b) = integral[a,b] t*g(t) dt
         = R/(2*pi) * (exp(-pi*a^2/R^2) - exp(-pi*b^2/R^2))

Uz = -Smax * I0x * I0y
Ux =  Smax/H * I1x * I0y
Uy =  Smax/H * I0x * I1y
```

Thus all three displacement components have an analytical reference, not just settlement. Complementary error functions are used in same-sign tails to avoid subtracting values rounded to 1. The tests additionally compare this reference with independently written tensor Gauss-Legendre quadrature for all components and several observation points.

For a transparent one-source calculation: a 2-by-2 m fragment centered at the origin, H=100 m, beta=45 degrees, and Smax=2 m gives `dS=2*4/100^2=0.0008 m` directly overhead. At `(100,0,0)`, `dS=0.0008*exp(-pi)`, Ux is `-dS`, Uy is zero, and Uz is `-dS`. Both the tests and the verification report check these hand-calculable values.

## Generated results and verification evidence

A `solve-flat` bundle contains all Phase 1 geometry artifacts plus:

| File | Contents |
| --- | --- |
| `model.json` | Complete flat-model settings |
| `displacement.npz` | Coordinates, combined displacement, separate Ux/Uy/Uz and positive settlement arrays |
| `displacement.csv` | Grid indices, coordinates, Ux/Uy/Uz and settlement in metres |
| `result_summary.json` | Conventions, geometry/settings, statistics, sampled peak, blocking and Python/NumPy versions |
| `displacement_maps.png` / `.svg` | Three scientific maps, signed horizontal color scales, extraction outlines and units |

The existing `summary.json` describes geometry; `result_summary.json` describes prediction. Numerical NPZ arrays load with `allow_pickle=False`. Saved projects/settings can be reopened and recomputed to reproduce the arrays. Export checks that the grid, settings and project match the result.

Generated local demonstration bundle: `outputs/phase2_flat`. Its 800 sources and 2,000 observation points give a maximum sampled settlement of **0.9100269318 m** for Smax=1 m and beta=20 degrees. The even observation grid samples x/y at ±10 m around the center; this sampled peak is distinct from the continuous analytical center settlement of **0.9143554105 m**. The remaining difference also includes source quadrature error.

Generated acceptance bundle: `outputs/phase2_verification`, containing `verification.json`, `verification.md`, saved benchmark inputs, `convergence.csv`, and PNG/SVG convergence figures. All **11 acceptance checks** pass: zero extraction, zero amplitude, center horizontal cancellation, x/y reflection, amplitude linearity, far-field decay, chunk equivalence, the transparent one-cell case, decreasing mesh error, and finest-mesh agreement.

All **50 automated tests** pass on Python 3.11.9: 25 retained Phase 1 checks and 25 Phase 2 checks. Tests also cover kernel normalization/support, exact station evaluation, shape/order, translated coordinates, surface elevations, overlap superposition, working-array bounds, invalid/inclined inputs, analytical tails, independently integrated references, and saved-result/CLI round trips. The maps and convergence figures were visually inspected.

The fixed convergence benchmark uses a 400-by-200 m panel at H=400 m, Smax=1 m, beta=20 degrees and the same 35 observation points at every refinement:

| Source spacing (m) | Sources | Maximum error across Ux/Uy/Uz (m) |
| --- | --- | --- |
| 40 | 50 | 0.00873848719 |
| 20 | 200 | 0.00218256455 |
| 10 | 800 | 0.000545401290 |
| 5 | 3,200 | 0.000136333766 |
| 2.5 | 12,800 | 0.0000340823830 |

Halving source spacing reduces error by approximately four, as expected for this smooth midpoint integration. The predefined finest-mesh maximum absolute tolerance is `2e-4 m`; symmetry, amplitude scaling and chunk equivalence use `1e-12 m`; the hand calculation uses `1e-15 m`; zero cases require exact zeros. These constants are set before the calculation in `subsidence/verification.py`.

These are numerical tolerances for this specified synthetic benchmark. The default 10 m demonstration mesh has about 0.545 mm maximum error on the verification points; it does not meet the finer mesh's 0.2 mm criterion. Other depths, influence angles, panel boundaries and source spacings need their own convergence assessment before calibration. Small R relative to source spacing can make midpoint integration inaccurate even when inputs are valid.

## Scope remaining

Phase 2 satisfies the flat-seam displacement acceptance criteria. Numerical verification demonstrates agreement with the selected equations and support convention. It does not reproduce Adriyala field RMSE or establish geological accuracy, improved field fit, horizontal-displacement validation, or strain validation.

Phase 3 adds strain derivatives and custom profiles. Phase 4 must resolve the inclined local/global transformation, depth, area and amplitude conventions before using the reported Adriyala geometry for prediction. Raw station coordinates and measurements are still missing; the reported 0.25 m / 0.26 m field errors remain source-reported values only.
