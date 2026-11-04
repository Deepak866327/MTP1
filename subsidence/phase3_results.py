"""Strain/profile artifacts and reuse of saved displacement grids."""

import csv
from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np

from .config import FlatModel, Project, load_flat_model, load_project, save_flat_model, save_project
from .deformation import StrainResult, horizontal_strain
from .geometry import ValidationError
from .grid_fields import displacement_digest, numeric_field, surface_axes
from .mesh import SurfaceGrid, build_surface_grid
from .plotting import save_profile_plot, save_strain_maps
from .profiles import ProfileResult, save_profiles
from .results import export_displacements
from .solver import DisplacementResult


def _new_directory(target: Path):
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValidationError(f"Output directory must be empty: {target}. Choose a new output path.")
    target.mkdir(parents=True, exist_ok=True)


def _json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def export_profiles(profiles: tuple[ProfileResult, ...], output: str | Path, *, project: Project, model: FlatModel, strain: StrainResult, source_run: str | None = None) -> dict:
    if not profiles or len({p.line.name for p in profiles}) != len(profiles):
        raise ValidationError("Export requires at least one profile with unique names.")
    digest = strain.metadata["source_displacement_sha256"]
    if any(p.metadata["source_displacement_sha256"] != digest for p in profiles):
        raise ValidationError("Profiles and strain must come from the same displacement grid.")
    target = Path(output)
    _new_directory(target)
    save_project(project, target / "project.json")
    save_flat_model(model, target / "model.json")
    save_profiles(tuple(p.line for p in profiles), target / "profiles.json")
    records = []
    for index, profile in enumerate(profiles, start=1):
        stem = f"profile_{index:03d}"  # User-entered names are never used as paths.
        np.savez_compressed(target / f"{stem}.npz", distance_m=profile.distance_m, xyz_m=profile.xyz_m, displacement_m=profile.displacement_m, ex=profile.ex, ey=profile.ey, ex_mm_per_m=profile.ex * 1000, ey_mm_per_m=profile.ey * 1000, boundary_influenced=profile.boundary_influenced)
        with (target / f"{stem}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["distance_m", "x_m", "y_m", "z_m", "ux_m", "uy_m", "uz_m", "ex", "ey", "ex_mm_per_m", "ey_mm_per_m", "boundary_influenced"])
            for k, distance in enumerate(profile.distance_m):
                writer.writerow([distance, *profile.xyz_m[k], *profile.displacement_m[k], profile.ex[k], profile.ey[k], profile.ex[k] * 1000, profile.ey[k] * 1000, int(profile.boundary_influenced[k])])
        save_profile_plot(profile, target, stem)
        records.append({"file_stem": stem, **profile.line.to_dict(), "length_m": profile.line.length_m, "boundary_influenced_sample_count": int(profile.boundary_influenced.sum()), "sampling": profile.metadata})
    summary = {"phase": 3, "evidence": project.evidence, "status": "global_field_profiles_no_field_validation", "source_run": source_run, "strain_method": strain.metadata, "profiles": records}
    _json(target / "profile_summary.json", summary)
    return summary


def export_deformation(project: Project, model: FlatModel, surface: SurfaceGrid, result: DisplacementResult, strain: StrainResult, output: str | Path, *, profiles: tuple[ProfileResult, ...] = ()) -> dict:
    surface_axes(surface, minimum_points=3)
    if not np.array_equal(strain.xyz_m, surface.xyz_m) or strain.metadata["source_displacement_sha256"] != displacement_digest(result.displacement_m):
        raise ValidationError("Strain does not match the displacement result and surface grid.")
    if profiles and (len({p.line.name for p in profiles}) != len(profiles) or any(p.metadata["source_displacement_sha256"] != strain.metadata["source_displacement_sha256"] for p in profiles)):
        raise ValidationError("Profile names must be unique and profiles must use the same displacement grid.")
    target = Path(output)
    export_displacements(project, model, surface, result, target)
    np.savez_compressed(target / "strain.npz", xyz_m=strain.xyz_m, ex=strain.ex, ey=strain.ey, ex_mm_per_m=strain.ex_mm_per_m, ey_mm_per_m=strain.ey_mm_per_m, boundary_mask=strain.boundary_mask)
    with (target / "strain.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["row_y", "col_x", "x_m", "y_m", "ex", "ey", "ex_mm_per_m", "ey_mm_per_m", "one_sided_boundary"])
        for row_y, col_x in np.ndindex(strain.ex.shape):
            writer.writerow([row_y, col_x, *strain.xyz_m[row_y, col_x, :2], strain.ex[row_y, col_x], strain.ey[row_y, col_x], strain.ex_mm_per_m[row_y, col_x], strain.ey_mm_per_m[row_y, col_x], int(strain.boundary_mask[row_y, col_x])])
    statistics = {}
    for label, values in (("ex", strain.ex), ("ey", strain.ey)):
        statistics[label] = {}
        for region, subset in (("all_cells", values), ("interior_only", values[~strain.boundary_mask])):
            statistics[label][region] = {"min": float(subset.min()), "max": float(subset.max()), "mean": float(subset.mean())}
    summary = {**strain.metadata, "name": project.name, "evidence": project.evidence, "status": "normal_horizontal_strain_no_field_validation", "statistics_dimensionless": statistics, "profile_count": len(profiles)}
    _json(target / "strain_summary.json", summary)
    save_strain_maps(project, surface, strain, target)
    if profiles:
        export_profiles(profiles, target / "profiles", project=project, model=model, strain=strain, source_run="..")
    return summary


@dataclass(frozen=True)
class SavedGridRun:
    project: Project
    model: FlatModel
    surface: SurfaceGrid
    displacement_m: np.ndarray


def load_grid_run(path: str | Path) -> SavedGridRun:
    """Read saved numeric arrays without calling the influence solver."""
    root = Path(path)
    project, model = load_project(root / "project.json"), load_flat_model(root / "model.json")
    try:
        with np.load(root / "geometry.npz", allow_pickle=False) as arrays:
            surface = SurfaceGrid(arrays["surface_xyz_m"], arrays["surface_x_edges_m"], arrays["surface_y_edges_m"])
        with np.load(root / "displacement.npz", allow_pickle=False) as arrays:
            if not np.array_equal(arrays["xyz_m"], surface.xyz_m):
                raise ValidationError("Saved displacement coordinates differ from the saved geometry grid.")
            displacement = arrays["displacement_m"]
    except KeyError as exc:
        raise ValidationError(f"Saved run is missing array: {exc}.") from exc
    surface_axes(surface, minimum_points=3)
    numeric_field(displacement, surface.xyz_m.shape, "Saved displacement")
    expected_surface = build_surface_grid(project)
    if not np.array_equal(expected_surface.xyz_m, surface.xyz_m) or not np.array_equal(expected_surface.x_edges_m, surface.x_edges_m) or not np.array_equal(expected_surface.y_edges_m, surface.y_edges_m):
        raise ValidationError("Saved geometry grid differs from the saved project.")
    metadata = json.loads((root / "result_summary.json").read_text(encoding="utf-8"))
    # Early Phase 2 example bundles omit the embedded project; their standalone
    # project, saved grid and model settings are still checked here.
    if metadata.get("project", project.to_dict()) != project.to_dict() or metadata.get("settings") != model.to_dict():
        raise ValidationError("Saved run project/model files differ from its recorded prediction inputs.")
    return SavedGridRun(project, model, surface, displacement)
