"""Bilinear sampling of the five global fields along arbitrary line segments."""

from dataclasses import dataclass
import json
import math
from numbers import Integral
from pathlib import Path

import numpy as np

from .config import _keys, _reject_constant, _unique_object
from .deformation import StrainResult
from .geometry import ValidationError, finite_number
from .grid_fields import displacement_digest, numeric_field, surface_axes
from .mesh import SurfaceGrid


MAX_PROFILE_SAMPLES = 1_000_000


def _point2(value, label):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValidationError(f"{label} must contain two finite numbers.")
    return tuple(finite_number(v, label) for v in value)


@dataclass(frozen=True)
class ProfileLine:
    name: str
    start_xy_m: tuple[float, float]
    end_xy_m: tuple[float, float]
    sample_count: int = 201

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValidationError("Profile name must be a nonempty string.")
        start, end = _point2(self.start_xy_m, "start_xy_m"), _point2(self.end_xy_m, "end_xy_m")
        distance = math.hypot(end[0] - start[0], end[1] - start[1])
        if not math.isfinite(distance) or distance == 0:
            raise ValidationError("Profile endpoints must define a finite nonzero length.")
        if isinstance(self.sample_count, bool) or not isinstance(self.sample_count, Integral) or not 2 <= self.sample_count <= MAX_PROFILE_SAMPLES:
            raise ValidationError(f"sample_count must be an integer from 2 to {MAX_PROFILE_SAMPLES:,}.")
        object.__setattr__(self, "start_xy_m", start)
        object.__setattr__(self, "end_xy_m", end)
        object.__setattr__(self, "sample_count", int(self.sample_count))

    @property
    def length_m(self):
        return math.hypot(self.end_xy_m[0] - self.start_xy_m[0], self.end_xy_m[1] - self.start_xy_m[1])

    def to_dict(self):
        return {"name": self.name, "start_xy_m": list(self.start_xy_m), "end_xy_m": list(self.end_xy_m), "sample_count": self.sample_count}


@dataclass(frozen=True)
class ProfileResult:
    line: ProfileLine
    distance_m: np.ndarray
    xyz_m: np.ndarray
    displacement_m: np.ndarray
    ex: np.ndarray
    ey: np.ndarray
    boundary_influenced: np.ndarray
    metadata: dict


def load_profiles(path: str | Path) -> tuple[ProfileLine, ...]:
    with Path(path).open(encoding="utf-8-sig") as handle:
        data = json.load(handle, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    _keys(data, ("schema_version", "units", "profiles"), label="profiles file")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValidationError("Only integer profile schema_version 1 is supported.")
    if data["units"] != {"length": "m"}:
        raise ValidationError("Profile coordinates must use units.length='m'.")
    if not isinstance(data["profiles"], list) or not data["profiles"]:
        raise ValidationError("profiles must be a nonempty list.")
    lines = []
    for item in data["profiles"]:
        _keys(item, ("name", "start_xy_m", "end_xy_m", "sample_count"), label="profile")
        lines.append(ProfileLine(**item))
    if len({line.name for line in lines}) != len(lines):
        raise ValidationError("Profile names must be unique.")
    return tuple(lines)


def save_profiles(lines: tuple[ProfileLine, ...], path: str | Path) -> None:
    data = {"schema_version": 1, "units": {"length": "m"}, "profiles": [line.to_dict() for line in lines]}
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def sample_profile(surface: SurfaceGrid, displacement_m, strain: StrainResult, line: ProfileLine) -> ProfileResult:
    x, y = surface_axes(surface)
    values = numeric_field(displacement_m, surface.xyz_m.shape, "Displacement")
    if not np.array_equal(strain.xyz_m, surface.xyz_m):
        raise ValidationError("Strain coordinates do not match the supplied surface grid.")
    if strain.metadata["source_displacement_sha256"] != displacement_digest(values):
        raise ValidationError("Strain was calculated from a different displacement field.")
    ex = numeric_field(strain.ex, values.shape[:2], "Ex")
    ey = numeric_field(strain.ey, values.shape[:2], "Ey")
    endpoints = np.array([line.start_xy_m, line.end_xy_m])
    if np.any(endpoints[:, 0] < x[0]) or np.any(endpoints[:, 0] > x[-1]) or np.any(endpoints[:, 1] < y[0]) or np.any(endpoints[:, 1] > y[-1]):
        raise ValidationError(f"Profile '{line.name}' must lie within the cell-center domain x=[{x[0]:g},{x[-1]:g}], y=[{y[0]:g},{y[-1]:g}]. Extrapolation is disabled.")
    xy = np.linspace(endpoints[0], endpoints[1], line.sample_count)
    ix = np.clip(np.searchsorted(x, xy[:, 0], side="right") - 1, 0, len(x) - 2)
    iy = np.clip(np.searchsorted(y, xy[:, 1], side="right") - 1, 0, len(y) - 2)
    tx, ty = (xy[:, 0] - x[ix]) / (x[ix + 1] - x[ix]), (xy[:, 1] - y[iy]) / (y[iy + 1] - y[iy])
    fields = np.concatenate([values, ex[..., None], ey[..., None]], axis=-1)
    sampled = np.zeros((line.sample_count, 5))
    boundary = np.zeros(line.sample_count, dtype=bool)
    for ox, oy, weight in ((0, 0, (1 - tx) * (1 - ty)), (1, 0, tx * (1 - ty)), (0, 1, (1 - tx) * ty), (1, 1, tx * ty)):
        sampled += weight[:, None] * fields[iy + oy, ix + ox]
        boundary |= (weight > 0) & strain.boundary_mask[iy + oy, ix + ox]
    xyz = np.column_stack([xy, np.full(line.sample_count, surface.xyz_m[0, 0, 2])])
    return ProfileResult(line, np.linspace(0, line.length_m, line.sample_count), xyz, sampled[:, :3], sampled[:, 3], sampled[:, 4], boundary, {
        "sampling": "Bilinear interpolation on actual cell centers; endpoints included; no extrapolation.",
        "displacement_units": "m",
        "strain_units": "dimensionless; display in mm/m = 1000*strain",
        "strain_components": "Global Ex=dUx/dx and Ey=dUy/dy, including on oblique lines; no directional projection.",
        "boundary_flag": "True if any nonzero interpolation weight uses a cell with a one-sided strain stencil.",
        "source_displacement_sha256": strain.metadata["source_displacement_sha256"],
    })
