"""Chunked gently inclined seam-frame Gaussian model, formulation v1.

This is a documented reconstruction. The unavailable original engine's exact
area/rotation/support conventions have not been independently established.
"""

import math
import platform

import numpy as np

from .config import InclinedModel, Project
from .geometry import ValidationError
from .mesh import build_source_mesh, build_surface_grid
from .seam_frame import SeamFrame
from .solver import DisplacementResult, evaluation_points, validate_chunks


MAX_DIP_DEG = 12.0


def inclined_geometry(project: Project, model: InclinedModel, xyz_m):
    if not isinstance(model, InclinedModel):
        raise ValidationError("The inclined solver requires InclinedModel settings.")
    if project.seam.dip_deg > MAX_DIP_DEG + 1e-10:
        raise ValidationError("Inclined prediction is supported only from 0 to 12 degrees of seam dip.")
    points = evaluation_points(project, xyz_m)
    frame = SeamFrame(project.seam)
    local = frame.points_to_local(points)
    h = local[..., 2]
    if np.any(~np.isfinite(h)) or np.any(h <= 0):
        raise ValidationError("Every evaluation point must lie above the seam plane with positive normal separation.")
    radii = h * math.tan(math.radians(model.influence_angle_deg))
    with np.errstate(over="ignore", under="ignore"):
        squares = radii * radii
    if np.any(~np.isfinite(squares)) or np.any(squares <= 0):
        raise ValidationError("Inclined influence radius squared must be positive and finite.")
    return points, frame, local, radii


def solve_inclined(project: Project, model: InclinedModel, xyz_m=None, *, observation_chunk_size: int = 128, source_chunk_size: int = 2048) -> DisplacementResult:
    validate_chunks(observation_chunk_size, source_chunk_size)
    if xyz_m is None:
        xyz_m = build_surface_grid(project).xyz_m
    points, frame, local_points, radii = inclined_geometry(project, model, xyz_m)
    sources = build_source_mesh(project)
    local_sources = frame.points_to_local(sources.xyz_m)
    flat_points = local_points.reshape(-1, 3)
    radii = radii.reshape(-1)
    nz = project.seam.unit_normal[2]
    local_smax = model.p_m / nz
    local_u = np.zeros_like(flat_points)
    if model.p_m and len(sources.xyz_m):
        try:
            with np.errstate(over="raise", invalid="raise", divide="raise"):
                for start in range(0, len(flat_points), observation_chunk_size):
                    p = flat_points[start:start + observation_chunk_size]
                    radius = radii[start:start + len(p), None]
                    h = p[:, 2]
                    total = local_u[start:start + len(p)]
                    for offset in range(0, len(local_sources), source_chunk_size):
                        a = local_sources[offset:offset + source_chunk_size]
                        dx, dy = a[None, :, 0] - p[:, None, 0], a[None, :, 1] - p[:, None, 1]
                        # Gaussian tails may underflow to zero; no cutoff is used.
                        with np.errstate(over="ignore", under="ignore"):
                            weights = np.exp(-math.pi * (np.square(dx / radius) + np.square(dy / radius))) / np.square(radius)
                        weights *= sources.seam_area_m2[None, offset:offset + len(a)]
                        weights *= local_smax
                        total[:, 0] += np.einsum("ij,ij->i", weights, dx) / h
                        total[:, 1] += np.einsum("ij,ij->i", weights, dy) / h
                        total[:, 2] -= weights.sum(axis=1)
                displacement = frame.vectors_to_global(local_u).reshape(points.shape)
        except FloatingPointError as exc:
            raise ValidationError("Inclined solver arithmetic exceeded numerical range.") from exc
    else:
        displacement = np.zeros_like(points)
    if not np.all(np.isfinite(displacement)):
        raise ValidationError("Inclined solver produced a nonfinite displacement.")

    def bounds(values):
        return [float(values.min()), float(values.max())] if values.size else None

    return DisplacementResult(points, displacement, sources, {
        "phase": 4, "model": "inclined_seam_frame_gaussian_v1", "integration": "source_fragment_midpoint_sum",
        "evidence": project.evidence,
        "formulation_status": "Explicit seam-frame reconstruction; exact original engine conventions remain unconfirmed.",
        "validation_scope": "Numerical verification only; no field validation or reproduced original RMSE.",
        "units": {"coordinates": "m", "displacement": "m", "source_area": "m^2", "angle": "degrees"},
        "components": ["Ux", "Uy", "Uz"],
        "sign_convention": "Global z upward; Uz negative downward; each global displacement contribution points toward its source.",
        "settings": model.to_dict(), "project": project.to_dict(),
        "unit_normal_xyz": list(project.seam.unit_normal), "dip_deg": project.seam.dip_deg,
        "basis_local_to_global": frame.basis.tolist(),
        "normal_depth_policy": "h=(P-reference) dot n; constant over all coplanar sources at fixed P; varies with observation location.",
        "normal_depth_range_m": bounds(flat_points[:, 2]), "influence_radius_range_m": bounds(radii),
        "area_measure": "seam_area = plan_area / unit_normal_z, applied once",
        "amplitude_policy": "Local normal amplitude Smax=p/unit_normal_z; p is in metres, equal to the infinite-panel vertical settlement limit.",
        "local_smax_m": local_smax,
        "kernel_policy": "Full Gaussian in seam-tangent coordinates; no hard cutoff or mined-part renormalization.",
        "source_count": len(sources.xyz_m), "evaluation_point_count": len(flat_points), "coordinate_shape": list(points.shape),
        "observation_chunk_size": int(observation_chunk_size), "source_chunk_size": int(source_chunk_size),
        "max_block_pairs": int(min(observation_chunk_size, len(flat_points)) * min(source_chunk_size, len(sources.xyz_m))),
        "python_version": platform.python_version(), "numpy_version": np.__version__,
    })
