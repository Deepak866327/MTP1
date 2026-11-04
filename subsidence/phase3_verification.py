"""Manufactured-field, interpolation and analytical derivative verification."""

import csv
from dataclasses import replace
import json
from pathlib import Path

from matplotlib.figure import Figure
import numpy as np

from .config import FlatModel, Project, Spacing, save_flat_model, save_project
from .deformation import horizontal_strain
from .mesh import SurfaceGrid, build_surface_grid
from .phase3_results import _new_directory
from .profiles import ProfileLine, sample_profile
from .reference import analytical_flat_displacement, analytical_flat_strain
from .solver import solve_flat
from .verification import verification_project


# Fixed before running: numerical verification only, not mine accuracy limits.
MANUFACTURED_ATOL = 1e-12
PROFILE_DISPLACEMENT_ATOL_M = 0.01
PROFILE_STRAIN_ATOL = 5e-5
FINE_STRAIN_ATOL = 2e-6
OBSERVATION_SPACINGS_M = (40.0, 20.0, 10.0, 5.0)


def manufactured_surface() -> SurfaceGrid:
    xe, ye = np.array([-6, -4, -1, 1, 4, 8.0]), np.array([-5, -3, 0, 2, 5.0])
    x, y = np.meshgrid(xe[:-1] + np.diff(xe) / 2, ye[:-1] + np.diff(ye) / 2, indexing="xy")
    return SurfaceGrid(np.stack([x, y, np.zeros_like(x)], axis=-1), xe, ye)


def bilinear_displacement(x, y):
    return np.stack([0.002 * x + 0.007 * y + 0.001 * x * y, -0.003 * y + 0.009 * x - 0.002 * x * y, 0.01 * x - 0.02 * y + 0.004 * x * y], axis=-1)


def run_deformation_verification() -> dict:
    surface = manufactured_surface()
    x, y = surface.xyz_m[..., 0], surface.xyz_m[..., 1]
    checks = []

    def add(name, value, tolerance, units):
        checks.append({"name": name, "passed": bool(value <= tolerance), "max_absolute_error": float(value), "absolute_tolerance": tolerance, "units": units})

    constant = horizontal_strain(surface, np.broadcast_to([1.0, -2.0, 3.0], surface.xyz_m.shape))
    add("constant_displacement_zero_strain", max(np.max(np.abs(constant.ex)), np.max(np.abs(constant.ey))), MANUFACTURED_ATOL, "dimensionless")
    affine = np.stack([0.002 * x + 0.007 * y + 1, -0.003 * y + 0.009 * x - 2, x + y], axis=-1)
    linear = horizontal_strain(surface, affine)
    add("affine_known_derivatives", max(np.max(np.abs(linear.ex - 0.002)), np.max(np.abs(linear.ey + 0.003))), MANUFACTURED_ATOL, "dimensionless")
    quadratic = np.stack([0.001 * x**2 + 0.005 * x * y, 0.002 * y**2 - 0.004 * x * y, x * 0], axis=-1)
    squared = horizontal_strain(surface, quadratic)
    add("nonuniform_quadratic_including_one_sided_boundaries", max(np.max(np.abs(squared.ex - (0.002 * x + 0.005 * y))), np.max(np.abs(squared.ey - (0.004 * y - 0.004 * x)))), MANUFACTURED_ATOL, "dimensionless")
    field = bilinear_displacement(x, y)
    strain = horizontal_strain(surface, field)
    line = ProfileLine("Manufactured oblique line", (-5, -4), (6, 3.5), 47)
    profile = sample_profile(surface, field, strain, line)
    px, py = profile.xyz_m[:, 0], profile.xyz_m[:, 1]
    add("bilinear_profile_displacement_exactness", np.max(np.abs(profile.displacement_m - bilinear_displacement(px, py))), MANUFACTURED_ATOL, "m")
    add("bilinear_profile_global_strain_exactness", max(np.max(np.abs(profile.ex - (0.002 + 0.001 * py))), np.max(np.abs(profile.ey - (-0.003 - 0.002 * px)))), MANUFACTURED_ATOL, "dimensionless")

    project, model = verification_project(), FlatModel(1, 20)
    actual_surface = build_surface_grid(project)
    result = solve_flat(project, model, actual_surface.xyz_m)
    actual_strain = horizontal_strain(actual_surface, result.displacement_m)
    actual_line = ProfileLine("Synthetic direct-solver comparison", (-350, -180), (350, 180), 81)
    sampled = sample_profile(actual_surface, result.displacement_m, actual_strain, actual_line)
    step = 0.25
    offsets = np.array([[0, 0, 0], [step, 0, 0], [-step, 0, 0], [0, step, 0], [0, -step, 0]])
    requested = sampled.xyz_m[None, ...] + offsets[:, None, :]
    direct = solve_flat(project, model, requested).displacement_m
    direct_ex = (direct[1, :, 0] - direct[2, :, 0]) / (2 * step)
    direct_ey = (direct[3, :, 1] - direct[4, :, 1]) / (2 * step)
    add("profile_vs_direct_displacement", np.max(np.abs(sampled.displacement_m - direct[0])), PROFILE_DISPLACEMENT_ATOL_M, "m")
    add("profile_vs_direct_small_step_strain", max(np.max(np.abs(sampled.ex - direct_ex)), np.max(np.abs(sampled.ey - direct_ey))), PROFILE_STRAIN_ATOL, "dimensionless")

    rows = []
    for spacing in OBSERVATION_SPACINGS_M:
        refined = replace(project, surface_grid=Spacing(spacing, spacing))
        grid = build_surface_grid(refined)
        # Exact displacement isolates FD error from source integration error.
        exact_displacement = analytical_flat_displacement(project, model, grid.xyz_m)
        derivatives = horizontal_strain(grid, exact_displacement)
        exact_strain = analytical_flat_strain(project, model, grid.xyz_m)
        error = np.abs(np.stack([derivatives.ex, derivatives.ey], axis=-1) - exact_strain)
        rows.append({"observation_spacing_m": spacing, "surface_point_count": int(np.prod(error.shape[:2])), "max_interior_strain_error": float(error[~derivatives.boundary_mask].max()), "max_boundary_strain_error": float(error[derivatives.boundary_mask].max()), "max_all_strain_error": float(error.max())})
    decreasing = all(b["max_interior_strain_error"] < a["max_interior_strain_error"] for a, b in zip(rows, rows[1:]))
    checks.append({"name": "derivative_refinement_error_decreases", "passed": decreasing})
    add("finest_analytical_strain_agreement", rows[-1]["max_all_strain_error"], FINE_STRAIN_ATOL, "dimensionless")
    return {
        "phase": 3, "evidence": "synthetic_numerical_verification_not_field_validation", "passed": all(c["passed"] for c in checks),
        "checks": checks, "strain_convergence": rows, "benchmark_project": project.to_dict(), "model": model.to_dict(),
        "manufactured_grid_edges_m": {"x": surface.x_edges_m.tolist(), "y": surface.y_edges_m.tolist()},
        "profile_comparison": {"line": actual_line.to_dict(), "direct_strain_difference_step_m": step, "source_spacing_m": [project.source_mesh.dx_m, project.source_mesh.dy_m], "surface_spacing_m": [project.surface_grid.dx_m, project.surface_grid.dy_m]},
        "implementation": {"python_version": result.metadata["python_version"], "numpy_version": np.__version__},
    }


def export_deformation_verification(report: dict, output: str | Path) -> None:
    target = Path(output)
    _new_directory(target)
    (target / "verification.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    save_project(Project.from_dict(report["benchmark_project"]), target / "project.json")
    save_flat_model(FlatModel.from_dict(report["model"]), target / "model.json")
    rows = report["strain_convergence"]
    with (target / "strain_convergence.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    figure = Figure(figsize=(7.5, 5), layout="constrained")
    axis = figure.subplots()
    spacing = np.array([row["observation_spacing_m"] for row in rows])
    errors = np.array([row["max_all_strain_error"] for row in rows]) * 1000
    axis.loglog(spacing, errors, "o-", label="Maximum Ex/Ey error, including boundaries")
    axis.loglog(spacing, errors[0] * (spacing / spacing[0])**2, "--", label="Second-order guide")
    axis.set(xlabel="Observation spacing (m)", ylabel="Maximum normal strain error (mm/m)", title="Derivative convergence on analytical flat-panel displacement")
    axis.grid(True, which="both", alpha=0.3)
    axis.legend(fontsize=9)
    figure.savefig(target / "strain_convergence.png", dpi=160)
    figure.savefig(target / "strain_convergence.svg")
    lines = ["# Phase 3 numerical verification", "", f"Overall result: {'PASS' if report['passed'] else 'FAIL'}.", "", "Synthetic manufactured fields and model comparisons only; no field validation.", "", "| Check | Result | Maximum absolute error | Fixed tolerance | Units |", "| --- | --- | --- | --- | --- |"]
    for check in report["checks"]:
        lines.append(f"| {check['name']} | {'PASS' if check['passed'] else 'FAIL'} | {check.get('max_absolute_error', 'n/a')} | {check.get('absolute_tolerance', 'n/a')} | {check.get('units', '')} |")
    lines.extend(["", "## Observation-grid derivative convergence", "", "Analytical displacement is differentiated on each grid and compared with analytical Ex/Ey, isolating finite-difference error from source quadrature.", "", "| Spacing (m) | Points | Interior maximum error | Boundary maximum error |", "| --- | --- | --- | --- |"])
    for row in rows:
        lines.append(f"| {row['observation_spacing_m']:g} | {row['surface_point_count']} | {row['max_interior_strain_error']:.9g} | {row['max_boundary_strain_error']:.9g} |")
    lines.extend(["", "Strain errors in the table are dimensionless; multiply by 1000 for mm/m. Thresholds are declared before calculation in subsidence/phase3_verification.py and apply to this benchmark only.", "", "Profiles contain global Ex/Ey on every line; they do not estimate arbitrary directional strain.", "", "![Derivative convergence](strain_convergence.png)", ""])
    (target / "verification.md").write_text("\n".join(lines), encoding="utf-8")
