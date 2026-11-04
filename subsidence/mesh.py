"""Independent midpoint meshes with exact rectangular boundary clipping."""

from dataclasses import dataclass
import math

import numpy as np

from .config import Project
from .geometry import ValidationError, union_tiles


DEFAULT_MAX_CELLS = 2_000_000


def axis_edges(start: float, stop: float, step: float, max_cells: int) -> np.ndarray:
    ratio = (stop - start) / step
    if not math.isfinite(ratio) or ratio > max_cells:
        raise ValidationError(f"Mesh axis exceeds the {max_cells:,}-cell limit; increase spacing.")
    nearest = round(ratio)
    # Avoid a spurious near-zero last cell when decimal spacings round upward.
    count = max(1, nearest if math.isclose(ratio, nearest, rel_tol=1e-13, abs_tol=1e-13) else math.ceil(ratio))
    edges = start + np.arange(count + 1, dtype=float) * step
    edges[-1] = stop
    if np.any(np.diff(edges) <= 0):
        raise ValidationError("Mesh spacing is below coordinate floating-point resolution.")
    return edges


@dataclass(frozen=True)
class SourceMesh:
    xyz_m: np.ndarray                 # (n_sources, 3)
    bounds_xy_m: np.ndarray           # (n_sources, 4): xmin,xmax,ymin,ymax
    plan_area_m2: np.ndarray          # (n_sources,)
    seam_area_m2: np.ndarray          # (n_sources,); plan_area / upward unit nz
    vertical_depth_m: np.ndarray      # surface elevation minus source z


@dataclass(frozen=True)
class SurfaceGrid:
    xyz_m: np.ndarray                 # (ny, nx, 3), x varies fastest on flattening
    x_edges_m: np.ndarray
    y_edges_m: np.ndarray


def _clip_axis(edges: np.ndarray, low: float, high: float) -> np.ndarray:
    inner = edges[np.searchsorted(edges, low, side="right"):np.searchsorted(edges, high, side="left")]
    return np.concatenate(([low], inner, [high]))


def build_source_mesh(project: Project, *, max_cells: int = DEFAULT_MAX_CELLS) -> SourceMesh:
    tiles = union_tiles(project.extraction_rectangles)
    if not tiles:
        return SourceMesh(np.empty((0, 3)), np.empty((0, 4)), np.empty(0), np.empty(0), np.empty(0))
    dx, dy = project.source_mesh.dx_m, project.source_mesh.dy_m
    x_edges = axis_edges(min(t.xmin_m for t in tiles), max(t.xmax_m for t in tiles), dx, max_cells)
    y_edges = axis_edges(min(t.ymin_m for t in tiles), max(t.ymax_m for t in tiles), dy, max_cells)
    bounds = []
    count = 0
    for tile in tiles:
        xe = _clip_axis(x_edges, tile.xmin_m, tile.xmax_m)
        ye = _clip_axis(y_edges, tile.ymin_m, tile.ymax_m)
        count += (len(xe) - 1) * (len(ye) - 1)
        if count > max_cells:
            raise ValidationError(f"Source mesh exceeds the {max_cells:,}-cell limit; increase spacing.")
        xl, yl = np.meshgrid(xe[:-1], ye[:-1], indexing="xy")
        xh, yh = np.meshgrid(xe[1:], ye[1:], indexing="xy")
        bounds.append(np.column_stack([xl.ravel(), xh.ravel(), yl.ravel(), yh.ravel()]))
    cells = np.concatenate(bounds)
    # Stable y-then-x order, independent of the ordering of input rectangles.
    cells = cells[np.lexsort((cells[:, 0], cells[:, 2]))]
    x = cells[:, 0] + (cells[:, 1] - cells[:, 0]) / 2
    y = cells[:, 2] + (cells[:, 3] - cells[:, 2]) / 2
    z = project.seam.z_at(x, y)
    area = (cells[:, 1] - cells[:, 0]) * (cells[:, 3] - cells[:, 2])
    return SourceMesh(
        np.column_stack([x, y, z]), cells, area,
        area / project.seam.unit_normal[2], project.surface_elevation_m - z,
    )


def build_surface_grid(project: Project, *, max_cells: int = DEFAULT_MAX_CELLS) -> SurfaceGrid:
    field = project.field
    xe = axis_edges(field.xmin_m, field.xmax_m, project.surface_grid.dx_m, max_cells)
    ye = axis_edges(field.ymin_m, field.ymax_m, project.surface_grid.dy_m, max_cells)
    if (len(xe) - 1) * (len(ye) - 1) > max_cells:
        raise ValidationError(f"Surface grid exceeds the {max_cells:,}-point limit; increase spacing.")
    x, y = np.meshgrid(xe[:-1] + np.diff(xe) / 2, ye[:-1] + np.diff(ye) / 2, indexing="xy")
    return SurfaceGrid(np.stack([x, y, np.full_like(x, project.surface_elevation_m)], axis=-1), xe, ye)
