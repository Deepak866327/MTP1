"""Chunked midpoint superposition of flat-seam displacement contributions."""

from dataclasses import dataclass
from numbers import Integral
import platform

import numpy as np

from .config import FlatModel, Project
from .geometry import ValidationError
from .influence import flat_depth_m, influence_radius_m, stochastic_kernel
from .mesh import SourceMesh, build_source_mesh, build_surface_grid


MAX_BLOCK_PAIRS = 1_048_576


def evaluation_points(project: Project, xyz_m) -> np.ndarray:
    """Accept station arrays or grids, with the final axis containing xyz."""
    values = np.asarray(xyz_m)
    if values.ndim < 1 or values.shape[-1] != 3 or values.dtype.kind not in "iuf":
        raise ValidationError("Evaluation points must be a numeric array with shape (...,3).")
    points = np.array(values, dtype=float, copy=True)
    if not np.all(np.isfinite(points)):
        raise ValidationError("Evaluation coordinates must be finite.")
    if not np.allclose(points[..., 2], project.surface_elevation_m, rtol=0, atol=1e-9):
        raise ValidationError("Evaluation points must lie on the configured horizontal surface (z tolerance 1e-9 m).")
    return points


@dataclass(frozen=True)
class DisplacementResult:
    xyz_m: np.ndarray
    displacement_m: np.ndarray        # same shape as xyz; components Ux, Uy, Uz
    sources: SourceMesh
    metadata: dict

    @property
    def ux_m(self):
        return self.displacement_m[..., 0]

    @property
    def uy_m(self):
        return self.displacement_m[..., 1]

    @property
    def uz_m(self):
        return self.displacement_m[..., 2]


def solve_flat(
    project: Project,
    model: FlatModel,
    xyz_m=None,
    *,
    observation_chunk_size: int = 128,
    source_chunk_size: int = 2048,
) -> DisplacementResult:
    """Predict at exact requested coordinates, or at the project's surface grid.

    Source and observation blocking limits pairwise temporary arrays. The
    returned arrays preserve the requested coordinate shape and order.
    """
    depth = flat_depth_m(project)
    radius = influence_radius_m(depth, model)
    for name, value in (("observation_chunk_size", observation_chunk_size), ("source_chunk_size", source_chunk_size)):
        if isinstance(value, bool) or not isinstance(value, Integral) or value <= 0:
            raise ValidationError(f"{name} must be a positive integer.")
    if observation_chunk_size * source_chunk_size > MAX_BLOCK_PAIRS:
        raise ValidationError(f"Chunk product exceeds the {MAX_BLOCK_PAIRS:,}-pair working-array limit.")
    if xyz_m is None:
        xyz_m = build_surface_grid(project).xyz_m
    points = evaluation_points(project, xyz_m)
    sources = build_source_mesh(project)
    flat_points = points.reshape(-1, 3)
    displacement = np.zeros_like(flat_points)
    if model.smax_m and len(sources.xyz_m):
        try:
            with np.errstate(over="raise", invalid="raise", divide="raise"):
                for start in range(0, len(flat_points), observation_chunk_size):
                    p = flat_points[start:start + observation_chunk_size]
                    total = displacement[start:start + len(p)]
                    for offset in range(0, len(sources.xyz_m), source_chunk_size):
                        a = sources.xyz_m[offset:offset + source_chunk_size]
                        dx = a[None, :, 0] - p[:, None, 0]
                        dy = a[None, :, 1] - p[:, None, 1]
                        weights = stochastic_kernel(np.hypot(dx, dy), radius)
                        weights *= sources.plan_area_m2[None, offset:offset + len(a)]
                        weights *= model.smax_m
                        total[:, 0] += np.einsum("ij,ij->i", weights, dx) / depth
                        total[:, 1] += np.einsum("ij,ij->i", weights, dy) / depth
                        total[:, 2] -= np.sum(weights, axis=1)
        except FloatingPointError as exc:
            raise ValidationError("Solver arithmetic exceeded numerical range; check coordinates, areas and amplitude.") from exc
    if not np.all(np.isfinite(displacement)):
        raise ValidationError("Solver produced a nonfinite displacement.")
    return DisplacementResult(points, displacement.reshape(points.shape), sources, {
        "phase": 2,
        "model": "flat_stochastic_gaussian",
        "integration": "source_fragment_midpoint_sum",
        "evidence": project.evidence,
        "validation_scope": "Numerical model; no field validation is implied.",
        "units": {"coordinates": "m", "displacement": "m", "source_area": "m^2", "angle": "degrees"},
        "components": ["Ux", "Uy", "Uz"],
        "sign_convention": "Global z upward; settlement Uz negative; positive settlement magnitude S=-Uz; horizontal contributions point toward each source.",
        "area_measure": "horizontal_plan_area (equal to seam area for a flat seam)",
        "depth_m": depth,
        "influence_radius_m": radius,
        "settings": model.to_dict(),
        "kernel_policy": "Full Gaussian over all mined sources; no radius cutoff or mined-area renormalization; full-plane integral 1.",
        "source_count": len(sources.xyz_m),
        "project": project.to_dict(),
        "evaluation_point_count": len(flat_points),
        "coordinate_shape": list(points.shape),
        "observation_chunk_size": int(observation_chunk_size),
        "source_chunk_size": int(source_chunk_size),
        "max_block_pairs": int(min(observation_chunk_size, len(flat_points)) * min(source_chunk_size, len(sources.xyz_m))),
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
    })
