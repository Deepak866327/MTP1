"""Independent high-order plan-coordinate integration for inclined verification."""

import math
from numbers import Integral

import numpy as np

from .config import InclinedModel, Project
from .geometry import ValidationError, union_tiles
from .solver import evaluation_points


def quadrature_inclined_displacement(project: Project, model: InclinedModel, xyz_m, *, order: int = 48) -> np.ndarray:
    """Gauss-Legendre rectangle integral using global vector projections.

    Does not use the midpoint mesh, SeamFrame or the inclined solver. It is a
    numerical reference rather than a closed-form solution or field evidence.
    """
    if isinstance(order, bool) or not isinstance(order, Integral) or not 2 <= order <= 256:
        raise ValidationError("Reference quadrature order must be an integer from 2 to 256.")
    if project.seam.dip_deg > 12 + 1e-10:
        raise ValidationError("Reference supports only the 0–12 degree inclined formulation.")
    points = evaluation_points(project, xyz_m)
    flat = points.reshape(-1, 3)
    result = np.zeros_like(flat)
    n = np.array(project.seam.unit_normal)
    h_values = (flat - project.seam.reference_xyz_m) @ n
    if np.any(h_values <= 0):
        raise ValidationError("Reference evaluation points require positive normal separation.")
    nodes, weights = np.polynomial.legendre.leggauss(order)
    for tile in union_tiles(project.extraction_rectangles):
        x = tile.xmin_m + tile.width_m * (nodes + 1) / 2
        y = tile.ymin_m + tile.height_m * (nodes + 1) / 2
        x, y = np.meshgrid(x, y, indexing="xy")
        sources = np.column_stack([x.ravel(), y.ravel(), project.seam.z_at(x, y).ravel()])
        areas = (np.outer(weights, weights) * tile.width_m * tile.height_m / (4 * n[2])).ravel()
        for i, (point, h) in enumerate(zip(flat, h_values)):
            d = point - sources
            q = d - h * n
            radius = h * math.tan(math.radians(model.influence_angle_deg))
            ds = (model.p_m / n[2]) * np.exp(-math.pi * np.sum(q * q, axis=1) / radius**2) / radius**2 * areas
            result[i] -= np.sum(ds[:, None] * d / h, axis=0)
    return result.reshape(points.shape)
