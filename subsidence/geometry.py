"""Global Cartesian geometry, metres, z positive upward."""

from dataclasses import dataclass, field
import math
from numbers import Real

import numpy as np


class ValidationError(ValueError):
    """A project or mesh input violates an explicit convention."""


def finite_number(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValidationError(f"{label} must be a finite number.")
    value = float(value)
    if not math.isfinite(value):
        raise ValidationError(f"{label} must be a finite number.")
    return value


def vector3(value, label: str) -> tuple[float, float, float]:
    if not isinstance(value, (tuple, list, np.ndarray)) or len(value) != 3:
        raise ValidationError(f"{label} must contain three numbers.")
    return tuple(finite_number(v, label) for v in value)


@dataclass(frozen=True)
class Rectangle:
    xmin_m: float
    xmax_m: float
    ymin_m: float
    ymax_m: float

    def __post_init__(self):
        for key in ("xmin_m", "xmax_m", "ymin_m", "ymax_m"):
            object.__setattr__(self, key, finite_number(getattr(self, key), key))
        if self.xmax_m <= self.xmin_m or self.ymax_m <= self.ymin_m:
            raise ValidationError("Rectangle maxima must exceed minima on both axes.")
        if not math.isfinite(self.width_m * self.height_m):
            raise ValidationError("Rectangle area exceeds numerical range.")

    @property
    def width_m(self) -> float:
        return self.xmax_m - self.xmin_m

    @property
    def height_m(self) -> float:
        return self.ymax_m - self.ymin_m

    @property
    def corners_xy_m(self) -> np.ndarray:
        return np.array([
            [self.xmin_m, self.ymin_m], [self.xmax_m, self.ymin_m],
            [self.xmax_m, self.ymax_m], [self.xmin_m, self.ymax_m],
        ])


@dataclass(frozen=True)
class SeamPlane:
    reference_xyz_m: tuple[float, float, float]
    normal_xyz: tuple[float, float, float]
    unit_normal: tuple[float, float, float] = field(init=False)

    def __post_init__(self):
        reference = vector3(self.reference_xyz_m, "seam.reference_xyz_m")
        normal = vector3(self.normal_xyz, "seam.normal_xyz")
        scale = max(abs(v) for v in normal)
        if scale == 0:
            raise ValidationError("Seam normal cannot be zero.")
        scaled = tuple(v / scale for v in normal)
        norm = math.hypot(*scaled)
        unit = tuple(v / norm for v in scaled)
        if abs(unit[2]) < 1e-12:
            raise ValidationError("Seam normal z component is too small for z(x,y).")
        if unit[2] < 0:
            unit = tuple(-v for v in unit)
        object.__setattr__(self, "reference_xyz_m", reference)
        object.__setattr__(self, "normal_xyz", normal)
        object.__setattr__(self, "unit_normal", unit)

    @property
    def dip_deg(self) -> float:
        return math.degrees(math.atan2(math.hypot(*self.unit_normal[:2]), self.unit_normal[2]))

    def z_at(self, x_m, y_m) -> np.ndarray:
        x, y = np.broadcast_arrays(np.asarray(x_m, dtype=float), np.asarray(y_m, dtype=float))
        if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
            raise ValidationError("Seam coordinates must be finite.")
        nx, ny, nz = self.unit_normal
        xr, yr, zr = self.reference_xyz_m
        with np.errstate(over="ignore", invalid="ignore"):
            z = zr - (nx * (x - xr) + ny * (y - yr)) / nz
        if not np.all(np.isfinite(z)):
            raise ValidationError("Seam elevation exceeds numerical range.")
        return z


def union_tiles(rectangles: tuple[Rectangle, ...]) -> tuple[Rectangle, ...]:
    """Disjoint x slabs with merged y intervals: exact axis-aligned rectangle union.

    Tiles may share edges but have no positive-area overlap. No geometry library
    or raster membership approximation is used.
    """
    edges = sorted({x for r in rectangles for x in (r.xmin_m, r.xmax_m)})
    tiles = []
    for left, right in zip(edges[:-1], edges[1:]):
        intervals = sorted(
            (r.ymin_m, r.ymax_m) for r in rectangles
            if r.xmin_m < right and r.xmax_m > left
        )
        merged = []
        for low, high in intervals:
            if merged and low <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], high)
            else:
                merged.append([low, high])
        tiles.extend(Rectangle(left, right, low, high) for low, high in merged)
    return tuple(tiles)


def union_plan_area_m2(rectangles: tuple[Rectangle, ...]) -> float:
    return math.fsum(r.width_m * r.height_m for r in union_tiles(rectangles))
