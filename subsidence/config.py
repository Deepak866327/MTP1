"""Strict project geometry and separate versioned flat-model settings."""

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path

import numpy as np

from .geometry import Rectangle, SeamPlane, ValidationError, finite_number


def _keys(data, required, optional=(), label="project"):
    if not isinstance(data, dict):
        raise ValidationError(f"{label} must be an object.")
    missing = set(required) - data.keys()
    extra = data.keys() - set(required) - set(optional)
    if missing:
        raise ValidationError(f"{label} is missing: {', '.join(sorted(missing))}.")
    if extra:
        raise ValidationError(f"Unknown {label} keys: {', '.join(sorted(extra))}.")


@dataclass(frozen=True)
class Spacing:
    dx_m: float
    dy_m: float

    def __post_init__(self):
        for name in ("dx_m", "dy_m"):
            value = finite_number(getattr(self, name), name)
            if value <= 0:
                raise ValidationError(f"{name} must be positive.")
            object.__setattr__(self, name, value)


@dataclass(frozen=True)
class Project:
    name: str
    evidence: str
    field: Rectangle
    seam: SeamPlane
    extraction_rectangles: tuple[Rectangle, ...]
    source_mesh: Spacing
    surface_grid: Spacing
    surface_elevation_m: float = 0.0
    provenance: dict = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValidationError("Project name must be a nonempty string.")
        if self.evidence not in ("synthetic_geometry", "reported_geometry", "custom_geometry"):
            raise ValidationError("evidence must be synthetic_geometry, reported_geometry, or custom_geometry.")
        if not isinstance(self.field, Rectangle) or not isinstance(self.seam, SeamPlane):
            raise ValidationError("field and seam must be Rectangle and SeamPlane objects.")
        if not isinstance(self.source_mesh, Spacing) or not isinstance(self.surface_grid, Spacing):
            raise ValidationError("source_mesh and surface_grid must be Spacing objects.")
        if not isinstance(self.extraction_rectangles, (list, tuple)) or not all(
            isinstance(r, Rectangle) for r in self.extraction_rectangles
        ):
            raise ValidationError("extraction_rectangles must be a list of rectangles (possibly empty).")
        if not isinstance(self.notes, (list, tuple)) or not all(isinstance(n, str) for n in self.notes):
            raise ValidationError("notes must be a list of strings.")
        if not isinstance(self.provenance, dict):
            raise ValidationError("provenance must be an object.")
        try:
            json.dumps(self.provenance, allow_nan=False)
        except (ValueError, TypeError) as exc:
            raise ValidationError("provenance must contain finite JSON values.") from exc
        object.__setattr__(self, "extraction_rectangles", tuple(self.extraction_rectangles))
        object.__setattr__(self, "notes", tuple(self.notes))
        elevation = finite_number(self.surface_elevation_m, "surface_elevation_m")
        object.__setattr__(self, "surface_elevation_m", elevation)
        if self.seam.reference_xyz_m[2] >= elevation:
            raise ValidationError("Seam reference must lie below the surface elevation.")
        # A plane's extrema over a rectangle occur at corners: checking centers
        # alone could miss a seam that intersects the surface along an edge.
        for index, rectangle in enumerate(self.extraction_rectangles):
            xy = rectangle.corners_xy_m
            if np.any(self.seam.z_at(xy[:, 0], xy[:, 1]) >= elevation):
                raise ValidationError(f"Extraction rectangle {index} reaches or crosses the surface.")

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "name": self.name,
            "evidence": self.evidence,
            "units": {"length": "m"},
            "surface_elevation_m": self.surface_elevation_m,
            "field": asdict(self.field),
            "seam": {
                "reference_xyz_m": list(self.seam.reference_xyz_m),
                "normal_xyz": list(self.seam.normal_xyz),
            },
            "extraction_rectangles": [asdict(r) for r in self.extraction_rectangles],
            "source_mesh": asdict(self.source_mesh),
            "surface_grid": asdict(self.surface_grid),
            "provenance": self.provenance,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Project":
        _keys(data, (
            "schema_version", "name", "evidence", "units", "surface_elevation_m",
            "field", "seam", "extraction_rectangles", "source_mesh", "surface_grid",
        ), ("provenance", "notes"))
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise ValidationError("Only integer schema_version 1 is supported.")
        if data["units"] != {"length": "m"}:
            raise ValidationError('units must be {"length": "m"}; coordinates use metres.')
        rectangle_keys = ("xmin_m", "xmax_m", "ymin_m", "ymax_m")
        _keys(data["field"], rectangle_keys, label="field")
        _keys(data["seam"], ("reference_xyz_m", "normal_xyz"), label="seam")
        for key in ("source_mesh", "surface_grid"):
            _keys(data[key], ("dx_m", "dy_m"), label=key)
        if not isinstance(data["extraction_rectangles"], list):
            raise ValidationError("extraction_rectangles must be an array.")
        for rectangle in data["extraction_rectangles"]:
            _keys(rectangle, rectangle_keys, label="extraction rectangle")
        return cls(
            name=data["name"], evidence=data["evidence"],
            field=Rectangle(**data["field"]), seam=SeamPlane(**data["seam"]),
            extraction_rectangles=tuple(Rectangle(**r) for r in data["extraction_rectangles"]),
            source_mesh=Spacing(**data["source_mesh"]), surface_grid=Spacing(**data["surface_grid"]),
            surface_elevation_m=data["surface_elevation_m"],
            provenance=data.get("provenance", {}), notes=data.get("notes", []),
        )


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"Duplicate JSON key: {key}.")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValidationError(f"Non-finite JSON value: {value}.")


def load_project(path: str | Path) -> Project:
    with Path(path).open(encoding="utf-8-sig") as handle:
        data = json.load(handle, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    return Project.from_dict(data)


def save_project(project: Project, path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(project.to_dict(), indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


@dataclass(frozen=True)
class FlatModel:
    """Smax is a settlement magnitude in metres, not a subsidence factor or p."""

    smax_m: float
    influence_angle_deg: float
    kernel_support: str = "full_gaussian"

    def __post_init__(self):
        amplitude = finite_number(self.smax_m, "smax_m")
        angle = finite_number(self.influence_angle_deg, "influence_angle_deg")
        if amplitude < 0:
            raise ValidationError("smax_m must be nonnegative (positive settlement magnitude).")
        if not 0 < angle < 90:
            raise ValidationError("influence_angle_deg must lie strictly between 0 and 90 degrees.")
        if self.kernel_support != "full_gaussian":
            raise ValidationError("Phase 2 supports only kernel_support='full_gaussian'.")
        object.__setattr__(self, "smax_m", amplitude)
        object.__setattr__(self, "influence_angle_deg", angle)

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "model": "flat_stochastic_gaussian",
            "units": {"length": "m", "angle": "degrees"},
            "smax_m": self.smax_m,
            "influence_angle_deg": self.influence_angle_deg,
            "kernel_support": self.kernel_support,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FlatModel":
        _keys(data, ("schema_version", "model", "units", "smax_m", "influence_angle_deg", "kernel_support"), label="flat model")
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise ValidationError("Only integer flat-model schema_version 1 is supported.")
        if data["model"] != "flat_stochastic_gaussian":
            raise ValidationError("Expected model='flat_stochastic_gaussian'.")
        if data["units"] != {"length": "m", "angle": "degrees"}:
            raise ValidationError("Flat-model units must be metres and degrees.")
        return cls(data["smax_m"], data["influence_angle_deg"], data["kernel_support"])


def load_flat_model(path: str | Path) -> FlatModel:
    with Path(path).open(encoding="utf-8-sig") as handle:
        data = json.load(handle, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    return FlatModel.from_dict(data)


def save_flat_model(model: FlatModel, path: str | Path) -> None:
    Path(path).write_text(json.dumps(model.to_dict(), indent=2, allow_nan=False) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class InclinedModel:
    """Versioned seam-frame reconstruction; conventions are explicit and fixed."""

    p_m: float
    influence_angle_deg: float
    kernel_support: str = "full_gaussian"
    depth_convention: str = "observation_to_plane_normal"
    area_measure: str = "seam_area"
    amplitude_convention: str = "p_over_unit_normal_z"

    def __post_init__(self):
        amplitude = finite_number(self.p_m, "p_m")
        if amplitude < 0:
            raise ValidationError("p_m must be nonnegative and measured in metres.")
        # Share the existing influence-angle/support rules without treating p as
        # Smax: the inclined local amplitude is computed separately as p/n_z.
        checked = FlatModel(amplitude, self.influence_angle_deg, self.kernel_support)
        for name, expected in (("depth_convention", "observation_to_plane_normal"), ("area_measure", "seam_area"), ("amplitude_convention", "p_over_unit_normal_z")):
            if getattr(self, name) != expected:
                raise ValidationError(f"Inclined v1 requires {name}='{expected}'.")
        object.__setattr__(self, "p_m", amplitude)
        object.__setattr__(self, "influence_angle_deg", checked.influence_angle_deg)

    def to_dict(self) -> dict:
        return {
            "schema_version": 1, "model": "inclined_seam_frame_gaussian_v1",
            "units": {"length": "m", "angle": "degrees"},
            "p_m": self.p_m, "influence_angle_deg": self.influence_angle_deg,
            "kernel_support": self.kernel_support, "depth_convention": self.depth_convention,
            "area_measure": self.area_measure, "amplitude_convention": self.amplitude_convention,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "InclinedModel":
        _keys(data, ("schema_version", "model", "units", "p_m", "influence_angle_deg", "kernel_support", "depth_convention", "area_measure", "amplitude_convention"), label="inclined model")
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise ValidationError("Only integer inclined-model schema_version 1 is supported.")
        if data["model"] != "inclined_seam_frame_gaussian_v1":
            raise ValidationError("Expected model='inclined_seam_frame_gaussian_v1'.")
        if data["units"] != {"length": "m", "angle": "degrees"}:
            raise ValidationError("Inclined-model units must be metres and degrees.")
        return cls(**{name: data[name] for name in ("p_m", "influence_angle_deg", "kernel_support", "depth_convention", "area_measure", "amplitude_convention")})


Model = FlatModel | InclinedModel


def load_model(path: str | Path) -> Model:
    with Path(path).open(encoding="utf-8-sig") as handle:
        data = json.load(handle, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    if not isinstance(data, dict):
        raise ValidationError("Model settings must be an object.")
    if data.get("model") == "flat_stochastic_gaussian":
        return FlatModel.from_dict(data)
    if data.get("model") == "inclined_seam_frame_gaussian_v1":
        return InclinedModel.from_dict(data)
    raise ValidationError("Unsupported model: expected flat_stochastic_gaussian or inclined_seam_frame_gaussian_v1.")


def save_model(model: Model, path: str | Path) -> None:
    Path(path).write_text(json.dumps(model.to_dict(), indent=2, allow_nan=False) + "\n", encoding="utf-8")
