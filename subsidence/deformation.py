"""Global normal horizontal strains, with explicit finite-difference boundaries."""

from dataclasses import dataclass

import numpy as np

from .geometry import ValidationError
from .grid_fields import displacement_digest, numeric_field, surface_axes
from .mesh import SurfaceGrid


@dataclass(frozen=True)
class StrainResult:
    xyz_m: np.ndarray
    ex: np.ndarray                    # dUx/dx, dimensionless
    ey: np.ndarray                    # dUy/dy, dimensionless
    boundary_mask: np.ndarray         # outer row/column: either strain uses a one-sided stencil
    metadata: dict

    @property
    def ex_mm_per_m(self):
        return 1000 * self.ex

    @property
    def ey_mm_per_m(self):
        return 1000 * self.ey


def horizontal_strain(surface: SurfaceGrid, displacement_m) -> StrainResult:
    x, y = surface_axes(surface, minimum_points=3)
    values = numeric_field(displacement_m, surface.xyz_m.shape, "Displacement")
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            ex = np.gradient(values[..., 0], x, axis=1, edge_order=2)
            ey = np.gradient(values[..., 1], y, axis=0, edge_order=2)
    except FloatingPointError as exc:
        raise ValidationError("Strain derivative exceeded numerical range; check coordinates and displacements.") from exc
    if not np.all(np.isfinite(ex)) or not np.all(np.isfinite(ey)):
        raise ValidationError("Strain calculation produced nonfinite values.")
    boundary = np.zeros(ex.shape, dtype=bool)
    boundary[[0, -1], :] = True
    boundary[:, [0, -1]] = True
    return StrainResult(np.array(surface.xyz_m, copy=True), ex, ey, boundary, {
        "phase": 3,
        "components": {"Ex": "dUx/dx along axis 1", "Ey": "dUy/dy along axis 0"},
        "units": "dimensionless (m/m); multiply by 1000 for mm/m",
        "sign_convention": "Positive tensile; negative compressive.",
        "derivative_method": "Three-point second-order differences using actual cell-center coordinates; centered on uniform interior grids, quadratic nonuniform formula otherwise.",
        "boundary_policy": "Second-order one-sided at first/last x centers for Ex and first/last y centers for Ey; boundary_mask is their union.",
        "boundary_cell_count": int(boundary.sum()),
        "interior_cell_count": int((~boundary).sum()),
        "source_displacement_sha256": displacement_digest(values),
        "coordinate_shape": list(surface.xyz_m.shape),
        "directional_strain": "Ex and Ey are global normal components. Shear and arbitrary directional strain are not calculated.",
        "validation_scope": "Numerical derivatives; no measured field strain validation.",
    })
