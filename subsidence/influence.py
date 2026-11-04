"""Full-support stochastic kernel; R is a scale, not a hard cutoff."""

import math

import numpy as np

from .config import FlatModel, Project
from .geometry import ValidationError, finite_number


def flat_depth_m(project: Project) -> float:
    nx, ny, _ = project.seam.unit_normal
    if nx != 0 or ny != 0:
        raise ValidationError("The flat solver requires a horizontal seam normal (0,0,+/-nz). Inclined seams require Phase 4.")
    depth = project.surface_elevation_m - project.seam.reference_xyz_m[2]
    if not math.isfinite(depth) or depth <= 0:
        raise ValidationError("Flat-seam depth must be positive and finite.")
    return depth


def influence_radius_m(depth_m: float, model: FlatModel) -> float:
    depth = finite_number(depth_m, "depth_m")
    if depth <= 0:
        raise ValidationError("depth_m must be positive.")
    radius = depth * math.tan(math.radians(model.influence_angle_deg))
    if not math.isfinite(radius) or not 0 < radius * radius < float("inf"):
        raise ValidationError("Influence radius squared is outside the finite positive numerical range.")
    return radius


def stochastic_kernel(r_m, radius_m: float) -> np.ndarray:
    """Phi(r) = exp(-pi*(r/R)^2)/R^2, units m^-2, integral over plane = 1."""
    radius = finite_number(radius_m, "radius_m")
    if radius <= 0 or not 0 < radius * radius < float("inf"):
        raise ValidationError("radius_m squared must be positive and finite.")
    distance = np.asarray(r_m, dtype=float)
    if np.any(~np.isfinite(distance)) or np.any(distance < 0):
        raise ValidationError("Kernel distances must be finite and nonnegative.")
    # Very distant finite points may overflow when squared; their Gaussian
    # contribution is correctly zero in float64. No spatial cutoff is applied.
    with np.errstate(over="ignore", under="ignore"):
        return np.exp(-math.pi * np.square(distance / radius)) / (radius * radius)
