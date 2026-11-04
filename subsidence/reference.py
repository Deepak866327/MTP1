"""Analytical Gaussian integrals, independent of source-cell quadrature."""

import math

import numpy as np

from .config import FlatModel, Project
from .geometry import union_tiles
from .influence import flat_depth_m, influence_radius_m
from .solver import evaluation_points


def _zeroth_moment(low: np.ndarray, high: np.ndarray) -> np.ndarray:
    """Half the erf difference; use erfc in tails to avoid subtracting two ones."""
    def interval(a, b):
        if a >= 0:
            return (math.erfc(a) - math.erfc(b)) / 2
        if b <= 0:
            return (math.erfc(-b) - math.erfc(-a)) / 2
        return (math.erf(b) - math.erf(a)) / 2
    return np.fromiter((interval(a, b) for a, b in zip(low, high)), dtype=float, count=len(low))


def _axis_integrals(low: float, high: float, points: np.ndarray, radius: float):
    """Return I0=integral g(t)dt and I1=integral t*g(t)dt, t=source-point."""
    a, b = (low - points) / radius, (high - points) / radius
    zeroth = _zeroth_moment(math.sqrt(math.pi) * a, math.sqrt(math.pi) * b)
    with np.errstate(over="ignore", under="ignore"):
        first = radius / (2 * math.pi) * (np.exp(-math.pi * a * a) - np.exp(-math.pi * b * b))
    return zeroth, first


def analytical_flat_displacement(project: Project, model: FlatModel, xyz_m) -> np.ndarray:
    """Exact full-support flat-rectangle integral, summed over disjoint union tiles.

    This reference never builds a source mesh or calls the numerical kernel.
    Its result is independent of source spacing.
    """
    depth = flat_depth_m(project)
    radius = influence_radius_m(depth, model)
    points = evaluation_points(project, xyz_m)
    flat = points.reshape(-1, 3)
    result = np.zeros_like(flat)
    for tile in union_tiles(project.extraction_rectangles):
        ix, jx = _axis_integrals(tile.xmin_m, tile.xmax_m, flat[:, 0], radius)
        iy, jy = _axis_integrals(tile.ymin_m, tile.ymax_m, flat[:, 1], radius)
        result[:, 0] += model.smax_m / depth * jx * iy
        result[:, 1] += model.smax_m / depth * ix * jy
        result[:, 2] -= model.smax_m * ix * iy
    return result.reshape(points.shape)
