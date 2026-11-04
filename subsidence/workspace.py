"""Desktop documents, cached scientific results and portable run archives.

This module has no GUI dependency. Display changes and reopening use saved
numeric arrays; only explicit compute/calibrate actions call the solvers.
"""

import base64
from dataclasses import dataclass, field, replace
import hashlib
import json
from pathlib import Path, PurePosixPath
import platform
import tempfile
import zipfile

import numpy as np

from .calibration import CalibrationResult, CalibrationSettings, calibrate_stations
from .config import FlatModel, InclinedModel, Project, load_model, load_project, _keys, _unique_object, _reject_constant
from .deformation import StrainResult, horizontal_strain
from .evaluation import BaselineResult, evaluate_stations, summarize_stations
from .geometry import ValidationError
from .grid_fields import numeric_field, surface_axes
from .inclined import solve_inclined
from .mesh import SurfaceGrid, build_source_mesh, build_surface_grid
from .observations import ObservationDataset, load_observations
from .phase3_results import _json, export_deformation, load_grid_run
from .phase5_results import export_baseline
from .phase6_results import export_calibration
from .profiles import ProfileLine, load_profiles, sample_profile
from .solver import DisplacementResult, solve_flat


FIELDS = {"Ux": "m", "Uy": "m", "Uz": "m", "Settlement": "m", "Ex": "mm/m", "Ey": "mm/m"}
COLORMAPS = ("viridis", "cividis", "plasma", "coolwarm", "RdBu_r")
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
EXAMPLES = ("Synthetic flat", "Synthetic inclined", "Adriyala reported geometry", "Synthetic calibration demo")


def example_document(name):
    if name == "Synthetic calibration demo":
        from .phase6_verification import synthetic_settings, write_synthetic_inputs
        with tempfile.TemporaryDirectory() as tmp:
            project, _, model, data = write_synthetic_inputs(Path(tmp) / "inputs", inclined=True)
        return ProjectDocument(project, model, observations=data, calibration_settings=synthetic_settings())
    files = {
        "Synthetic flat": ("synthetic_flat.json", "flat_model.json", "profiles.json"),
        "Synthetic inclined": ("synthetic_inclined.json", "inclined_model.json", "profiles.json"),
        "Adriyala reported geometry": ("adriyala_geometry.json", "adriyala_inclined_model.json", "adriyala_profiles.json"),
    }
    if name not in files:
        raise ValidationError("Choose a supplied example.")
    root = Path(__file__).resolve().parents[1] / "examples"
    project, model, profiles = [root / p for p in files[name]]
    return ProjectDocument(load_project(project), load_model(model), load_profiles(profiles))


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)


def model_from_dict(value):
    if not isinstance(value, dict):
        raise ValidationError("Model must be an object.")
    if value.get("model") == "flat_stochastic_gaussian":
        return FlatModel.from_dict(value)
    if value.get("model") == "inclined_seam_frame_gaussian_v1":
        return InclinedModel.from_dict(value)
    raise ValidationError("Unsupported model identifier.")


def observations_from_bytes(csv_bytes, metadata_bytes):
    # Reuse the strict Phase 5 loader, preserving exact original bytes.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "observations.csv").write_bytes(csv_bytes)
        (root / "metadata.json").write_bytes(metadata_bytes)
        return load_observations(root / "observations.csv", root / "metadata.json")


@dataclass(frozen=True)
class ProjectDocument:
    project: Project
    model: FlatModel | InclinedModel
    profiles: tuple[ProfileLine, ...] = ()
    observations: ObservationDataset | None = None
    calibration_settings: CalibrationSettings | None = None
    selected_field: str = "Uz"
    colormap: str = "viridis"

    def __post_init__(self):
        if not isinstance(self.project, Project) or not isinstance(self.model, (FlatModel, InclinedModel)):
            raise ValidationError("Desktop document requires valid project and model settings.")
        if self.selected_field not in FIELDS or self.colormap not in COLORMAPS:
            raise ValidationError("Unsupported display field or color map.")
        if any(not isinstance(p, ProfileLine) for p in self.profiles) or len({p.name for p in self.profiles}) != len(self.profiles):
            raise ValidationError("Profile definitions require unique names.")
        if self.calibration_settings is not None and not isinstance(self.calibration_settings, CalibrationSettings):
            raise ValidationError("Invalid calibration settings.")
        if self.observations is not None and not isinstance(self.observations, ObservationDataset):
            raise ValidationError("Invalid observation dataset.")

    def to_dict(self):
        data = None if self.observations is None else {
            "csv_base64": base64.b64encode(self.observations.raw_csv).decode("ascii"),
            "metadata_base64": base64.b64encode(self.observations.raw_metadata).decode("ascii"),
        }
        return {"schema_version": 1, "application": "subsidence_desktop", "project": self.project.to_dict(), "model": self.model.to_dict(), "profiles": [p.to_dict() for p in self.profiles], "observations": data, "calibration_settings": None if self.calibration_settings is None else self.calibration_settings.to_dict(), "selected_field": self.selected_field, "colormap": self.colormap}

    @classmethod
    def from_dict(cls, data):
        _keys(data, ("schema_version", "application", "project", "model", "profiles", "observations", "calibration_settings", "selected_field", "colormap"), label="desktop document")
        if type(data["schema_version"]) is not int or data["schema_version"] != 1 or data["application"] != "subsidence_desktop":
            raise ValidationError("Unsupported desktop document schema/application.")
        if not isinstance(data["profiles"], list):
            raise ValidationError("profiles must be an array.")
        lines = []
        for line in data["profiles"]:
            _keys(line, ("name", "start_xy_m", "end_xy_m", "sample_count"), label="profile")
            lines.append(ProfileLine(**line))
        observations = None
        if data["observations"] is not None:
            _keys(data["observations"], ("csv_base64", "metadata_base64"), label="embedded observations")
            try:
                observations = observations_from_bytes(*(base64.b64decode(data["observations"][key], validate=True) for key in ("csv_base64", "metadata_base64")))
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"Invalid embedded observation data: {exc}") from exc
        settings = data["calibration_settings"]
        return cls(Project.from_dict(data["project"]), model_from_dict(data["model"]), tuple(lines), observations, None if settings is None else CalibrationSettings.from_dict(settings), data["selected_field"], data["colormap"])


def save_document(document, path):
    _json(Path(path), document.to_dict())


def load_document(path):
    return ProjectDocument.from_dict(_read_json(path))


def physics_key(document):
    return json.dumps([document.project.to_dict(), document.model.to_dict()], sort_keys=True, allow_nan=False)


def observation_key(dataset):
    return None if dataset is None else (dataset.csv_sha256, hashlib.sha256(dataset.raw_metadata).hexdigest())


@dataclass
class ApplicationRun:
    document: ProjectDocument
    surface: SurfaceGrid
    displacement: DisplacementResult
    strain: StrainResult
    evaluation: BaselineResult | None = None
    calibration: CalibrationResult | None = None
    calibration_summary: dict | None = None
    calibration_assets: dict[str, bytes] = field(default_factory=dict)

    def matches(self, document):
        return physics_key(self.document) == physics_key(document) and observation_key(self.document.observations) == observation_key(document.observations)

    def values(self, name):
        if name not in FIELDS:
            raise ValidationError("Select a known displacement/strain field.")
        return {"Ux": self.displacement.ux_m, "Uy": self.displacement.uy_m, "Uz": self.displacement.uz_m, "Settlement": -self.displacement.uz_m, "Ex": self.strain.ex_mm_per_m, "Ey": self.strain.ey_mm_per_m}[name]

    def statistics(self, name):
        values = self.values(name)
        return {"minimum": float(values.min()), "maximum": float(values.max()), "mean": float(values.mean()), "unit": FIELDS[name]}

    def profile(self, line):
        return sample_profile(self.surface, self.displacement.displacement_m, self.strain, line)

    def inspect(self, x, y, name):
        if not np.isfinite(x) or not np.isfinite(y) or not self.surface.x_edges_m[0] <= x <= self.surface.x_edges_m[-1] or not self.surface.y_edges_m[0] <= y <= self.surface.y_edges_m[-1]:
            return None
        ix = int(np.clip(np.searchsorted(self.surface.x_edges_m, x, side="right") - 1, 0, len(self.surface.x_edges_m) - 2))
        iy = int(np.clip(np.searchsorted(self.surface.y_edges_m, y, side="right") - 1, 0, len(self.surface.y_edges_m) - 2))
        return {"x_m": float(self.surface.xyz_m[iy, ix, 0]), "y_m": float(self.surface.xyz_m[iy, ix, 1]), "value": float(self.values(name)[iy, ix]), "unit": FIELDS[name], "one_sided_boundary": bool(self.strain.boundary_mask[iy, ix])}


def compute_document(document):
    surface = build_surface_grid(document.project)
    surface_axes(surface, minimum_points=3)
    _validate_profiles(document, surface)
    solver = solve_inclined if isinstance(document.model, InclinedModel) else solve_flat
    result = solver(document.project, document.model, surface.xyz_m)
    strain = horizontal_strain(surface, result.displacement_m)
    evaluation = None if document.observations is None else evaluate_stations(document.project, document.model, document.observations)
    return ApplicationRun(document, surface, result, strain, evaluation)


def calibrate_document(document):
    if document.observations is None or document.calibration_settings is None:
        raise ValidationError("Load station observations and specify calibration bounds/starts first.")
    surface = build_surface_grid(document.project)
    surface_axes(surface, minimum_points=3)
    _validate_profiles(document, surface)
    calibration = calibrate_stations(document.project, document.model, document.observations, document.calibration_settings)
    document = replace(document, model=calibration.fitted_model)
    # Recompute maps once for the selected model; station evaluation is reused.
    solver = solve_inclined if isinstance(document.model, InclinedModel) else solve_flat
    displacement = solver(document.project, document.model, surface.xyz_m)
    return ApplicationRun(document, surface, displacement, horizontal_strain(surface, displacement.displacement_m), calibration.fitted, calibration)


def _validate_profiles(document, surface):
    x, y = surface_axes(surface)
    for line in document.profiles:
        points = np.array([line.start_xy_m, line.end_xy_m])
        if np.any(points[:, 0] < x[0]) or np.any(points[:, 0] > x[-1]) or np.any(points[:, 1] < y[0]) or np.any(points[:, 1] > y[-1]):
            raise ValidationError(f"Profile '{line.name}' must be inside cell centers x=[{x[0]:g},{x[-1]:g}], y=[{y[0]:g},{y[-1]:g}]. Edit/remove the line before computing.")


def export_run(run, path):
    """Write a complete portable ZIP, refusing to overwrite any existing file."""
    path = Path(path)
    if path.exists():
        raise ValidationError("Choose a new run filename; existing runs are never overwritten.")
    if run.displacement.metadata["project"] != run.document.project.to_dict() or run.displacement.metadata["settings"] != run.document.model.to_dict():
        raise ValidationError("Computed arrays differ from current settings. Compute before exporting.")
    if observation_key(run.document.observations) != observation_key(None if run.evaluation is None else run.evaluation.dataset):
        raise ValidationError("Observations differ from the computed station comparison.")
    profiles = tuple(run.profile(line) for line in run.document.profiles)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        save_document(run.document, root / "desktop_project.json")
        export_deformation(run.document.project, run.document.model, run.surface, run.displacement, run.strain, root / "grid", profiles=profiles)
        if run.evaluation is not None:
            export_baseline(run.document.project, run.document.model, run.evaluation, root / "stations")
        if run.calibration is not None:
            run.calibration_summary = export_calibration(run.calibration, root / "calibration")
        elif run.calibration_assets:
            for name, data in run.calibration_assets.items():
                # Names originate only from validated archive entries.
                _safe_name(name)
                dest = root / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
        (root / "README.md").write_text("# Subsidence desktop saved run\n\nOpen this ZIP using the application's Open run button. desktop_project.json retains configuration and provenance; grid contains exact displacement and derived strain arrays, CSVs and PNG/SVG plots. Optional stations and calibration folders retain observations, comparisons and optimization settings.\n\nCoordinates and displacement: metres, global z upward. Positive settlement=-Uz. Ex/Ey: dimensionless in arrays, mm/m in display (1000 times strain); positive tensile. One-sided boundaries are flagged. Synthetic evidence is not field validation; original inclined conventions remain unresolved.\n", encoding="utf-8")
        members = [p for p in root.rglob("*") if p.is_file()]
        if len(members) >= 2000 or sum(p.stat().st_size for p in members) > MAX_ARCHIVE_BYTES - 1024 * 1024:
            raise ValidationError("Run exceeds portable archive limits. Reduce the grid/profile sizes before exporting.")
        files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in members}
        _json(root / "manifest.json", {"format": "subsidence_desktop_run_v1", "phase": 7, "python": platform.python_version(), "files_sha256": files})
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation also protects against another writer creating it.
        try:
            with path.open("xb") as handle:
                with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    for item in sorted(root.rglob("*")):
                        if item.is_file():
                            archive.write(item, item.relative_to(root).as_posix())
        except FileExistsError as exc:
            raise ValidationError("Run filename already exists.") from exc


def _safe_name(name):
    path = PurePosixPath(name)
    if not name or "\\" in name or ":" in name or path.is_absolute() or any(part in ("..", ".") for part in name.split("/")) or "" in name.split("/"):
        raise ValidationError("Unsafe path in run archive.")


def _restore_directory(root):
    document = load_document(root / "desktop_project.json")
    grid = load_grid_run(root / "grid")
    if document.project.to_dict() != grid.project.to_dict() or document.model != grid.model:
        raise ValidationError("Run document and computed grid settings differ.")
    _validate_profiles(document, grid.surface)
    metadata = _read_json(root / "grid/result_summary.json")
    result = DisplacementResult(grid.surface.xyz_m, grid.displacement_m, build_source_mesh(grid.project), metadata)
    strain = horizontal_strain(grid.surface, grid.displacement_m)
    with np.load(root / "grid/strain.npz", allow_pickle=False) as arrays:
        for name, expected in (("xyz_m", strain.xyz_m), ("ex", strain.ex), ("ey", strain.ey), ("boundary_mask", strain.boundary_mask)):
            if not np.array_equal(arrays[name], expected):
                raise ValidationError("Saved strain does not match displacement arrays.")
    evaluation = None
    if document.observations is not None:
        data = load_observations(root / "stations/raw_observations.csv", root / "stations/raw_metadata.json")
        if observation_key(data) != observation_key(document.observations):
            raise ValidationError("Archived observations differ from the run document.")
        with np.load(root / "stations/station_predictions.npz", allow_pickle=False) as arrays:
            xyz = numeric_field(arrays["xyz_m"], (len(data.stations), 3), "Station coordinates")
            if not np.all(xyz[:, 2] == document.project.surface_elevation_m):
                raise ValidationError("Archived stations differ from surface elevation.")
            station_metadata = _read_json(root / "stations/baseline_summary.json")["solver"]
            if station_metadata["settings"] != document.model.to_dict() or station_metadata["project"] != document.project.to_dict():
                raise ValidationError("Archived station settings differ from the run.")
            prediction = DisplacementResult(xyz, arrays["displacement_m"], result.sources, station_metadata)
            evaluation = summarize_stations(data, prediction)
            if not np.array_equal(arrays["residual_m"], evaluation.residual_m) or not np.array_equal(arrays["uz_observed_m"], [s.uz_observed_m for s in data.stations]):
                raise ValidationError("Archived station residuals are inconsistent.")
    run = ApplicationRun(document, grid.surface, result, strain, evaluation)
    if (root / "calibration").is_dir():
        run.calibration_summary = _read_json(root / "calibration/calibration_summary.json")
        if run.calibration_summary.get("fitted_model") != document.model.to_dict():
            raise ValidationError("Archived calibration model differs from grid settings.")
        if document.observations is None or run.calibration_summary.get("csv_sha256") != document.observations.csv_sha256 or run.calibration_summary.get("metadata_sha256") != hashlib.sha256(document.observations.raw_metadata).hexdigest() or _read_json(root / "calibration/project.json") != document.project.to_dict():
            raise ValidationError("Archived calibration evidence differs from the run document.")
        run.calibration_assets = {p.relative_to(root).as_posix(): p.read_bytes() for p in (root / "calibration").rglob("*") if p.is_file()}
    return run


def open_run(path):
    """Verify archive paths/hashes before reading numeric arrays; never unpickle."""
    path = Path(path)
    if path.is_dir():
        # Compatibility with earlier CLI deformation/grid bundles.
        grid = load_grid_run(path)
        profiles = load_profiles(path / "profiles/profiles.json") if (path / "profiles/profiles.json").exists() else ()
        doc = ProjectDocument(grid.project, grid.model, profiles)
        result = DisplacementResult(grid.surface.xyz_m, grid.displacement_m, build_source_mesh(grid.project), _read_json(path / "result_summary.json"))
        return ApplicationRun(doc, grid.surface, result, horizontal_strain(grid.surface, grid.displacement_m))
    try:
        with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory() as tmp:
            members = archive.infolist()
            if len(members) > 2000 or sum(i.file_size for i in members) > MAX_ARCHIVE_BYTES or len({i.filename for i in members}) != len(members):
                raise ValidationError("Run archive exceeds limits or contains duplicate paths.")
            for item in members:
                _safe_name(item.filename)
                if item.is_dir() or (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValidationError("Run archive must contain regular files only.")
            if "manifest.json" not in archive.namelist():
                raise ValidationError("Missing run manifest.")
            manifest = json.loads(archive.read("manifest.json"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            _keys(manifest, ("format", "phase", "python", "files_sha256"), label="run manifest")
            hashes = manifest["files_sha256"]
            if manifest["format"] != "subsidence_desktop_run_v1" or not isinstance(hashes, dict) or set(hashes) != set(archive.namelist()) - {"manifest.json"}:
                raise ValidationError("Unsupported/incomplete run manifest.")
            root = Path(tmp)
            for name, expected in hashes.items():
                raw = archive.read(name)
                if hashlib.sha256(raw).hexdigest() != expected:
                    raise ValidationError(f"Run integrity check failed for {name}.")
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            return _restore_directory(root)
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ValidationError(f"Invalid/incomplete saved run: {exc}") from exc
