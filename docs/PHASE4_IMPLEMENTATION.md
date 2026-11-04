# Phase 4: gently inclined seam reconstruction

Implemented 4 November 2026 against Phase 4 of the rebuild plan. The numerical core now supports planar seams with dip from 0 to 12 degrees, transforms complete displacement vectors between seam and ground coordinates, and reuses the existing Ex/Ey/profile/export pipeline. Phase 4 is recorded as a separate commit after Phase 3 `693841d` on `main`.

The model is named **inclined_seam_frame_gaussian_v1**. It is a fully specified reconstruction of the reported geometry-based method. The original engine's complete code, exact area convention, fitted-amplitude interpretation and raw monitoring data remain unavailable. Numerical agreement with the chosen equations is distinguished from exact source-engine reproduction and field validation throughout the outputs.

## Source evidence and decisions

Scanned MTP PDF pp.16–19 and 21–22 were visually checked again. Source statements are:

| Evidence | Source | Implementation interpretation |
| --- | --- | --- |
| Retain the stochastic kernel and change geometry | pp.16–19, Eq.5–6 | Gaussian evaluated in seam-related coordinates |
| Calculate local displacement and transform it back | p.19, text after Eq.6 | Orthonormal seam basis; rotate vectors without translating them |
| Decompose the source-to-surface vector into normal depth and radial components | p.21, Eq.9 | Signed normal distance and seam-tangent radial distance |
| `Smax=p/n_s^z` | p.22, Eq.10; enlarged image `docs/source_extracts/eq10_detail.png` | Denominator is the unit normal's z component, not a square |
| Kernel multiplied by `dx*dy` | p.22, Eq.11 | Report does not fully establish whether these are plan or seam coordinates |
| Movement follows the source-to-surface direction | p.22, text after Eq.11 | Local normal increment plus tangential components, then full vector rotation |

The explicit rebuild decisions are **normal separation**, **seam-tangent radius**, **seam-area integration**, **local normal amplitude p/nz**, and **full Gaussian support**. The basis uses a continuous minimal rotation from global +z to the seam normal. Those choices make the integral and its zero-dip limit consistent. They are recorded in model files and metadata rather than silently attributed to the original C++ program. This formulation does not substitute Luo's separate asymmetric influence function.

The source's p=1.3 m versus later Smax=1.3 m naming remains a source discrepancy. For this model, p and local Smax are distinct when dip is nonzero. The report also describes a peak shifting toward the shallower side; the selected seam-normal reconstruction's symmetric-panel dip study shifts toward the positive-normal horizontal direction (down dip for the example). That qualitative difference is logged rather than corrected by changing an undocumented sign. Phase 5 must compare actual source plots and monitoring coordinates before making a reproduction claim.

## Geometry and transformations

Let `n=(nx,ny,nz)` be the normalized upward seam normal, A0 its reference point, A a source on the plane, and P a surface evaluation point. Source z still comes from the Phase 1 plane equation:

```text
z_A = z_ref - (nx*(x_A-x_ref) + ny*(y_A-y_ref)) / nz
d = P - A
h = dot(P-A0, n) = dot(P-A, n)
q = d - h*n
r = norm(q)
```

All sources are coplanar. Consequently h is the same for every source at a fixed P, although source vertical depths vary. h changes when P moves along dip. Using each source's vertical depth in this formulation would define a different model. Positive normal separation is required for every evaluation point, including zero-amplitude/empty-extraction runs. A point outside the observation field can be evaluated if it lies on the configured horizontal surface and above the seam plane's extension.

The local-to-global basis B has columns local e1, e2, n:

```text
c = 1 + nz
B = [[1-nx*nx/c, -nx*ny/c, nx],
     [-nx*ny/c, 1-ny*ny/c, ny],
     [-nx,      -ny,      nz]]

point_local  = (point_global - A0) @ B
point_global = point_local @ B.T + A0
vector_local = vector_global @ B
vector_global = vector_local @ B.T
```

B is orthonormal and right handed and equals the identity at zero dip. It avoids the undefined strike direction that a strike/dip basis would have at zero dip. Because the tangential kernel is isotropic, the arbitrary choice of orthonormal tangent axes does not create a physical preferred direction. `SeamFrame` supports numeric arrays of any shape ending in 3. Point transforms include the origin; vector transforms do not.

The verification bundle includes `coordinate_diagram.png`/`.svg`, showing A, P, the normal projection Q, q, and h*n in a true-scale dip section.

## Integral, area and amplitude specification

For each clipped source fragment, `dA_seam=dA_plan/nz` is its exact planar surface area, up to floating-point rounding. For local tangential offsets toward the source, `tx=A_local_x-P_local_x` and `ty=A_local_y-P_local_y`:

```text
R(P) = h(P) * tan(influence_angle)
Smax_local = p / nz
Phi = exp(-pi*(tx^2+ty^2)/R^2) / R^2
dS_local = Smax_local * Phi * dA_seam

dU_local = (dS_local*tx/h, dS_local*ty/h, -dS_local)
dU_global = dU_local @ B.T
U_global = sum(dU_global)
```

Both h and R depend on P. No hard influence-radius cutoff or normalization over just the mined portion is used. The same full-support policy as Phase 2 is retained. Phi has units m^-2, area has units m² and p/Smax/displacement have units m. Normal, influence angle and tangential directions have separate names.

The rotation implies the useful independent identity:

```text
dU_global = -dS_local * (P-A) / h
```

Thus each contribution points toward its source and has negative global Uz when the source is below the horizontal surface. dS_local is the **local normal component**, not the norm of the whole displacement vector. Normalizing P-A to unit length and multiplying by dS_local would fail to recover the Phase 2 horizontal/vertical relationship.

The area Jacobian and amplitude factor each appear once and serve different roles. For a formal full-seam-plane Gaussian integral at fixed P, `integral Phi*dA_seam=1` and the tangential first moment is zero. Then `U=-(p/nz)*n`, whose global Uz is `-p`. This explains the amplitude convention. The unbounded integral is a mathematical normalization, not a physically infinite inclined panel below a horizontal surface. A finite broad, still-buried panel checks this limit numerically.

At zero dip, n=(0,0,1), B=I, h=H, seam area=plan area and Smax_local=p. Every displacement component reduces to the flat solver with Smax=p. Zero-dip strain and profile outputs are also checked against Phase 2/3.

## Settings and supported workflow

`InclinedModel` uses a strict version-1 file with explicit conventions:

```json
{
  "schema_version": 1,
  "model": "inclined_seam_frame_gaussian_v1",
  "units": {"length": "m", "angle": "degrees"},
  "p_m": 1.0,
  "influence_angle_deg": 20.0,
  "kernel_support": "full_gaussian",
  "depth_convention": "observation_to_plane_normal",
  "area_measure": "seam_area",
  "amplitude_convention": "p_over_unit_normal_z"
}
```

p must be nonnegative and the influence angle strictly between 0 and 90 degrees. Other convention strings are rejected so a run cannot silently change formulation. Seam dip is checked against 0–12 degrees in the solver (with 1e-10 degree round-off allowance). The Phase 1 geometry preview can still inspect steeper seams, but prediction rejects them.

`load_model`/`save_model` dispatch flat and inclined settings. Existing `load_flat_model`, `solve-flat`, and `deform-flat` remain flat-only and compatible with prior examples. Generic displacement/strain/profile exports and saved-run loading retain the model's actual settings. The default source/observation blocks remain 2,048/128, with a maximum chunk product of 1,048,576 pairs; no complete source-by-observation array is allocated.

From the workspace in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m subsidence deform-inclined examples/synthetic_inclined.json --model examples/inclined_model.json --profiles examples/profiles.json --output outputs/inclined_prediction
.\.venv\Scripts\python.exe -m subsidence verify-inclined --output outputs/inclined_verification
.\.venv\Scripts\python.exe -m subsidence deform-inclined examples/adriyala_geometry.json --model examples/adriyala_inclined_model.json --profiles examples/adriyala_profiles.json --output outputs/adriyala_reconstruction
.\.venv\Scripts\python.exe -m subsidence sample-profiles outputs/inclined_prediction --profiles examples/profiles.json --output outputs/inclined_profiles
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`solve-inclined` exports displacement only. `deform-inclined` additionally computes global Ex/Ey and optional profiles. The existing actual-coordinate derivatives, boundary flags, mm/m conversion and center-domain interpolation rules apply. Strains are calculated **after** displacement rotation to global coordinates. Oblique profiles retain global Ex/Ey and do not infer directional strain or shear. Outputs require new/empty directories; saved arrays load with `allow_pickle=False`.

Python usage:

```python
from subsidence import load_project, load_model, solve_inclined

project = load_project("examples/synthetic_inclined.json")
model = load_model("examples/inclined_model.json")
grid = solve_inclined(project, model)
stations = solve_inclined(project, model, [[0, 0, 0], [0, 100, 0]])
print(stations.displacement_m)
```

The package is version 0.4.0. Direct dependencies remain NumPy 2.4.6 and Matplotlib 3.10.8; no additional dependency is required.

## Numerical verification

All **102 tests** pass, retaining the previous 76 checks and adding 26 Phase 4 tests. The deterministic verification report has **27 passing checks**, including multiple dip-specific point/vector round trips. Checks cover zero dip, source-plane placement, orthonormal/right-handed basis, normal scaling/sign and reference invariance, amplitude linearity, empty/zero cases, bounds and shapes, chunk equivalence, translated datums, horizontal rotation/reflection covariance and small dip-increment continuity. Tests also cover one-cell hand calculations, broad-panel amplitude normalization, settings rejection, saved-run recomputation and inclined profile reuse without a solver rerun.

An independent reference uses Gauss-Legendre integration in global plan coordinates, reconstructs source z directly, forms q by vector projection, and integrates `-dS*(P-A)/h`. It never uses source midpoint cells, SeamFrame, or the production inclined solver. Orders 48 and 64 differ by at most `8.44e-15 m` on the benchmark; the declared order-stability tolerance is `1e-10 m`. The zero-dip quadrature also agrees with the analytical flat integral.

For the 400-by-200 m synthetic panel at reference depth 400 m, 10-degree dip, p=1 m and influence angle 20 degrees, all components are compared at the same 35 points:

| Source spacing (m) | Sources | Maximum Ux/Uy/Uz error against quadrature (m) |
| --- | --- | --- |
| 40 | 50 | 0.00845316776 |
| 20 | 200 | 0.00209864195 |
| 10 | 800 | 0.000523715408 |
| 5 | 3,200 | 0.000130869389 |
| 2.5 | 12,800 | 0.0000327136249 |

The finest error is about **0.033 mm**, below the predefined `2e-4 m` benchmark tolerance. Zero-dip displacement differs from the flat solver by at most `1.11e-16 m` on the verification points, against a `1e-12 m` tolerance. Point round trips use `1e-10 m`; vector/basis/covariance checks use `1e-12`. Dip increments of `1e-4 degrees` produce changes up to `4.85e-6 m`, below a predeclared `5e-5 m` continuity threshold. These thresholds are fixed in `phase4_verification.py` and apply to this numerical benchmark only.

The report exports saved inputs, explicit reference points/values, convergence CSV/plots, the coordinate diagram, and a dip study at 0/3/6/10/12 degrees. Asymmetry alone is recorded as a qualitative diagnostic, not proof of correctness or original-project reproduction.

## Generated demonstrations and remaining evidence

- `outputs/phase4_inclined`: 10-degree synthetic panel, 800 sources, 2,000 grid points, global displacement/strain maps and 3 profiles. Maximum sampled settlement is 0.9146553644 m at (-10,70,0) m under this convention.
- `outputs/phase4_verification`: all 27 checks pass; includes `coordinate_diagram`, `dip_profiles`, `convergence`, and `verification.md`.
- `outputs/phase4_adriyala_reconstruction`: reported geometry with explicit p=1.3 m/beta=20 degree settings, 5,775 sources, 10,857 observations, and 2 computational centerline profiles. Maximum sampled settlement is 1.2624743893 m at (2085,175,0) m. The reported screenshot minimum is approximately -1.277 m; proximity is not field validation or evidence of an identical original implementation.

Adriyala's unit normal gives local Smax=1.3213121805 m. Normal observation-to-plane distances over the cropped grid range from 345.0579893 to 469.6809120 m. These differ from source vertical depths, as expected. The physical versus computational panel length/depth differences remain preserved. Computational centerlines are model sections, not invented monitoring stations.

The implementation satisfies the numerical/geometry acceptance criteria for the explicitly selected inclined formulation. It does not establish the original engine's exact area/support/amplitude conventions, reconcile the report's up-dip wording, or reproduce the reported 0.25/0.26 m RMSE. Phase 5 needs original code or additional equation clarification where available, plus actual station coordinates, observations, datum and measurement stage. Until then, retain the reconstruction label and make no improved-accuracy claim.
