"""Shared validation for cell-centered rectilinear field calculations."""

import hashlib

import numpy as np

from .geometry import ValidationError
from .mesh import SurfaceGrid


def surface_axes(surface: SurfaceGrid, *, minimum_points: int = 2):
    xyz = np.asarray(surface.xyz_m)
    if xyz.ndim != 3 or xyz.shape[-1] != 3 or xyz.dtype.kind not in "iuf" or not np.all(np.isfinite(xyz)):
        raise ValidationError("Surface coordinates must be finite numeric (ny,nx,3) arrays.")
    ny, nx, _ = xyz.shape
    if min(ny, nx) < minimum_points:
        raise ValidationError(f"This operation requires at least {minimum_points} cell centers on each surface axis.")
    x, y = xyz[0, :, 0], xyz[:, 0, 1]
    if np.any(np.diff(x) <= 0) or np.any(np.diff(y) <= 0):
        raise ValidationError("Surface x and y coordinates must be strictly increasing.")
    if not np.array_equal(xyz[..., 0], np.broadcast_to(x, (ny, nx))) or not np.array_equal(xyz[..., 1], np.broadcast_to(y[:, None], (ny, nx))):
        raise ValidationError("Surface must be a rectilinear grid with x on axis 1 and y on axis 0.")
    if not np.all(xyz[..., 2] == xyz[0, 0, 2]):
        raise ValidationError("Surface grid must be horizontal.")
    for edges, centers, label in ((surface.x_edges_m, x, "x"), (surface.y_edges_m, y, "y")):
        edges = np.asarray(edges)
        if edges.shape != (len(centers) + 1,) or edges.dtype.kind not in "iuf" or not np.all(np.isfinite(edges)) or np.any(np.diff(edges) <= 0):
            raise ValidationError(f"Surface {label} edges must be finite and strictly increasing with n+1 entries.")
        if not np.allclose(edges[:-1] + np.diff(edges) / 2, centers, rtol=0, atol=1e-9):
            raise ValidationError(f"Surface {label} coordinates must be the cell centers of its edges.")
    return np.asarray(x, dtype=float), np.asarray(y, dtype=float)


def numeric_field(values, shape, label: str) -> np.ndarray:
    values = np.asarray(values)
    if values.shape != shape or values.dtype.kind not in "iuf" or not np.all(np.isfinite(values)):
        raise ValidationError(f"{label} must be finite numeric values with shape {shape}.")
    return np.asarray(values, dtype=float)


def displacement_digest(values: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(values, dtype="<f8")).hexdigest()
