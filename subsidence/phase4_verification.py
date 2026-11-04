"""Inclined-seam numerical verification and coordinate diagrams."""

import csv
from dataclasses import replace
import json
import math
from pathlib import Path

from matplotlib.figure import Figure
import numpy as np

from .config import FlatModel, InclinedModel, Project, Spacing, save_model, save_project
from .geometry import Rectangle, SeamPlane
from .inclined import solve_inclined
from .inclined_reference import quadrature_inclined_displacement
from .phase3_results import _new_directory
from .seam_frame import SeamFrame
from .solver import solve_flat
from .verification import verification_project


ALGEBRA_ATOL_M = 1e-12
ROUND_TRIP_ATOL_M = 1e-10
FINE_MESH_ATOL_M = 2e-4
QUADRATURE_ATOL_M = 1e-10
CONTINUITY_ATOL_M = 5e-5
SPACINGS_M = (40.0, 20.0, 10.0, 5.0, 2.5)


def normal_at_dip(dip_deg: float):
    angle = math.radians(dip_deg)
    return (0.0, math.sin(angle), math.cos(angle))


def inclined_benchmark(dip_deg=10.0) -> Project:
    p = verification_project()
    return replace(p, name=f"Synthetic inclined verification: {dip_deg:g} degrees", seam=SeamPlane((0, 0, -400), normal_at_dip(dip_deg)))


def quarter_turn(project: Project) -> Project:
    """Physical 90-degree horizontal rotation, retaining rectangular geometry."""
    def rect(r):
        return Rectangle(-r.ymax_m, -r.ymin_m, r.xmin_m, r.xmax_m)
    x, y, z = project.seam.reference_xyz_m
    nx, ny, nz = project.seam.normal_xyz
    return replace(project, field=rect(project.field), seam=SeamPlane((-y, x, z), (-ny, nx, nz)), extraction_rectangles=tuple(rect(r) for r in project.extraction_rectangles), source_mesh=Spacing(project.source_mesh.dy_m, project.source_mesh.dx_m), surface_grid=Spacing(project.surface_grid.dy_m, project.surface_grid.dx_m))


def run_inclined_verification() -> dict:
    p, model = inclined_benchmark(), InclinedModel(1, 20)
    x, y = np.meshgrid(np.linspace(-300, 300, 7), np.linspace(-200, 200, 5), indexing="xy")
    points = np.stack([x, y, np.zeros_like(x)], axis=-1)
    checks = []

    def add(name, value, tolerance):
        checks.append({"name": name, "passed": bool(value <= tolerance), "max_absolute_error": float(value), "absolute_tolerance": tolerance})

    flat_project = inclined_benchmark(0)
    zero_dip = solve_inclined(flat_project, model, points)
    flat = solve_flat(flat_project, FlatModel(1, 20), points)
    add("zero_dip_all_displacement_components", np.max(np.abs(zero_dip.displacement_m - flat.displacement_m)), ALGEBRA_ATOL_M)
    rng = np.random.default_rng(4829)
    xyz = rng.normal(size=(100, 3)) * 500
    vectors = rng.normal(size=(100, 3))
    for dip in (0, 1e-7, 3, 6, 10, 12):
        frame = SeamFrame(inclined_benchmark(dip).seam)
        add(f"point_round_trip_{dip:g}_deg", np.max(np.abs(frame.points_to_global(frame.points_to_local(xyz)) - xyz)), ROUND_TRIP_ATOL_M)
        add(f"vector_round_trip_{dip:g}_deg", np.max(np.abs(frame.vectors_to_global(frame.vectors_to_local(vectors)) - vectors)), ALGEBRA_ATOL_M)
    frame = SeamFrame(p.seam)
    add("basis_orthogonality", np.max(np.abs(frame.basis.T @ frame.basis - np.eye(3))), ALGEBRA_ATOL_M)
    add("basis_right_handed", abs(np.linalg.det(frame.basis) - 1), ALGEBRA_ATOL_M)
    base = solve_inclined(p, model, points)
    add("source_points_on_local_plane", np.max(np.abs(frame.points_to_local(base.sources.xyz_m)[:, 2])), ALGEBRA_ATOL_M)
    add("zero_extraction", np.max(np.abs(solve_inclined(replace(p, extraction_rectangles=()), model, points).displacement_m)), 0)
    add("zero_amplitude", np.max(np.abs(solve_inclined(p, InclinedModel(0, 20), points).displacement_m)), 0)
    doubled = solve_inclined(p, InclinedModel(2, 20), points)
    add("amplitude_linearity", np.max(np.abs(doubled.displacement_m - 2 * base.displacement_m)), ALGEBRA_ATOL_M)
    blocked = solve_inclined(p, model, points, observation_chunk_size=3, source_chunk_size=37)
    add("chunk_equivalence", np.max(np.abs(blocked.displacement_m - base.displacement_m)), ALGEBRA_ATOL_M)

    # Dip in both x/y directions exercises covariance beyond a symmetric y-dip.
    slant = replace(p, seam=SeamPlane((0, 0, -400), (0.08, 0.15, 1)))
    original = solve_inclined(slant, model, points)
    reflected = replace(slant, seam=SeamPlane((0, 0, -400), (-0.08, 0.15, 1)))
    reflected_u = solve_inclined(reflected, model, points * [-1, 1, 1])
    add("horizontal_reflection_covariance", np.max(np.abs(reflected_u.displacement_m - original.displacement_m * [-1, 1, 1])), ALGEBRA_ATOL_M)
    rotated_points = points[..., [1, 0, 2]] * [-1, 1, 1]
    rotated_u = solve_inclined(quarter_turn(slant), model, rotated_points)
    expected = original.displacement_m[..., [1, 0, 2]] * [-1, 1, 1]
    add("quarter_turn_covariance", np.max(np.abs(rotated_u.displacement_m - expected)), ALGEBRA_ATOL_M)

    jumps = []
    for dip in (0, 3, 6, 10, 11.999):
        before = solve_inclined(inclined_benchmark(dip), model, points)
        after = solve_inclined(inclined_benchmark(dip + 1e-4), model, points)
        jumps.append(float(np.max(np.abs(after.displacement_m - before.displacement_m))))
    add("small_dip_increment_continuity", max(jumps), CONTINUITY_ATOL_M)

    exact = quadrature_inclined_displacement(p, model, points, order=48)
    higher = quadrature_inclined_displacement(p, model, points, order=64)
    add("independent_quadrature_order_stability", np.max(np.abs(exact - higher)), QUADRATURE_ATOL_M)
    rows = []
    for spacing in SPACINGS_M:
        result = solve_inclined(replace(p, source_mesh=Spacing(spacing, spacing)), model, points)
        error = np.abs(result.displacement_m - higher)
        rows.append({"source_spacing_m": spacing, "source_count": len(result.sources.xyz_m), "max_ux_error_m": float(error[..., 0].max()), "max_uy_error_m": float(error[..., 1].max()), "max_uz_error_m": float(error[..., 2].max()), "max_component_error_m": float(error.max())})
    checks.append({"name": "mesh_error_strictly_decreases", "passed": all(b["max_component_error_m"] < a["max_component_error_m"] for a, b in zip(rows, rows[1:]))})
    add("finest_mesh_reference_agreement", rows[-1]["max_component_error_m"], FINE_MESH_ATOL_M)
    pair = solve_inclined(p, model, [[0, -100, 0], [0, 100, 0]])
    asymmetric_difference = abs(float(pair.uz_m[0] - pair.uz_m[1]))
    checks.append({"name": "asymmetric_trough_qualitative", "passed": asymmetric_difference > 1e-4, "vertical_difference_m": asymmetric_difference, "interpretation": "Qualitative only; asymmetry does not establish model or field accuracy."})
    return {
        "phase": 4, "evidence": "synthetic_numerical_verification_not_field_validation", "passed": all(c["passed"] for c in checks),
        "formulation": "inclined_seam_frame_gaussian_v1; documented reconstruction, exact original conventions unconfirmed",
        "benchmark_project": p.to_dict(), "model": model.to_dict(), "checks": checks, "convergence": rows,
        "verification_points_xyz_m": points.reshape(-1, 3).tolist(), "reference_displacement_m": higher.reshape(-1, 3).tolist(),
        "dip_increment_deg": 1e-4, "basis_local_to_global": frame.basis.tolist(),
        "implementation": {"python_version": base.metadata["python_version"], "numpy_version": np.__version__},
    }


def save_coordinate_diagram(project: Project, output: Path):
    """A true-scale y/z section through the synthetic benchmark's dip direction."""
    figure = Figure(figsize=(8, 6), layout="constrained")
    axis = figure.subplots()
    n = np.array(project.seam.unit_normal)
    a = np.array(project.seam.reference_xyz_m)
    p = np.array([0.0, 210, project.surface_elevation_m])
    h = float((p - a) @ n)
    q = p - h * n
    ys = np.array([-200, 250])
    axis.plot(ys, project.seam.z_at(np.zeros_like(ys), ys), color="#b86d18", label="Seam plane")
    axis.axhline(project.surface_elevation_m, color="#397da5", label="Horizontal ground surface")
    for start, end, label, color in ((a, p, "d = P - A", "#888888"), (a, q, "q (seam-tangent offset)", "#b86d18"), (q, p, "h n (normal separation)", "#30986b")):
        axis.annotate("", xy=end[1:], xytext=start[1:], arrowprops={"arrowstyle": "->", "color": color, "linewidth": 1.8})
        midpoint = (start + end) / 2
        offset = (-90, 3) if label.startswith("d =") else ((-35, -18) if label.startswith("q (") else (8, 3))
        axis.annotate(label, midpoint[1:], xytext=offset, textcoords="offset points", fontsize=9, color=color)
    for point, label in ((a, "A: extracted source"), (p, "P: surface evaluation"), (q, "Q: normal projection")):
        axis.plot(point[1], point[2], "o", color="#263b4a")
        axis.annotate(label, point[1:], xytext=(5, -15), textcoords="offset points", fontsize=9)
    axis.set(xlabel="Global y (m)", ylabel="Global z (m), positive upward", title="Phase 4 seam-normal decomposition (10-degree synthetic seam)", aspect="equal", ylim=(-470, 60), xlim=(-200, 370))
    axis.grid(True, alpha=0.2)
    axis.legend(loc="upper right")
    figure.savefig(output / "coordinate_diagram.png", dpi=160)
    figure.savefig(output / "coordinate_diagram.svg")


def export_inclined_verification(report: dict, output: str | Path):
    target = Path(output)
    _new_directory(target)
    (target / "verification.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    project, model = Project.from_dict(report["benchmark_project"]), InclinedModel.from_dict(report["model"])
    save_project(project, target / "project.json")
    save_model(model, target / "model.json")
    with (target / "convergence.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(report["convergence"][0]))
        writer.writeheader()
        writer.writerows(report["convergence"])
    with (target / "reference_points.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["x_m", "y_m", "z_m", "reference_ux_m", "reference_uy_m", "reference_uz_m"])
        writer.writerows([*p, *u] for p, u in zip(report["verification_points_xyz_m"], report["reference_displacement_m"]))
    figure = Figure(figsize=(7.5, 5), layout="constrained")
    axis = figure.subplots()
    rows = report["convergence"]
    spacing = np.array([r["source_spacing_m"] for r in rows])
    error = np.array([r["max_component_error_m"] for r in rows])
    axis.loglog(spacing, error, "o-", label="Maximum Ux/Uy/Uz error vs independent quadrature")
    axis.loglog(spacing, error[0] * (spacing / spacing[0])**2, "--", label="Second-order guide")
    axis.set(xlabel="Source spacing (m)", ylabel="Maximum absolute displacement error (m)", title="Inclined seam-frame midpoint convergence")
    axis.grid(True, which="both", alpha=0.3)
    axis.legend(fontsize=9)
    figure.savefig(target / "convergence.png", dpi=160)
    figure.savefig(target / "convergence.svg")
    figure = Figure(figsize=(8, 5), layout="constrained")
    axis = figure.subplots()
    y = np.linspace(-350, 350, 141)
    points = np.column_stack([np.zeros_like(y), y, np.zeros_like(y)])
    for dip in (0, 3, 6, 10, 12):
        result = solve_inclined(inclined_benchmark(dip), model, points)
        axis.plot(y, result.uz_m, label=f"{dip} degrees")
    axis.set(xlabel="Global y (m), x=0", ylabel="Uz (m), negative downward", title="Synthetic dip study — explicit seam-frame reconstruction")
    axis.grid(True, alpha=0.3)
    axis.legend()
    figure.savefig(target / "dip_profiles.png", dpi=160)
    figure.savefig(target / "dip_profiles.svg")
    save_coordinate_diagram(project, target)
    lines = ["# Phase 4 inclined numerical verification", "", f"Overall result: {'PASS' if report['passed'] else 'FAIL'}.", "", "Explicit seam-frame reconstruction; original engine conventions and field RMSE have not been independently reproduced.", "", "| Check | Result | Error / diagnostic | Tolerance |", "| --- | --- | --- | --- |"]
    for check in report["checks"]:
        lines.append(f"| {check['name']} | {'PASS' if check['passed'] else 'FAIL'} | {check.get('max_absolute_error', check.get('vertical_difference_m', 'n/a'))} | {check.get('absolute_tolerance', 'n/a')} |")
    lines.extend(["", "## Source-mesh convergence", "", "Independent reference: global-coordinate Gauss-Legendre integration; orders 48 and 64 cross-checked. Same 35 observation points at each refinement.", "", "| Source spacing (m) | Sources | Maximum component error (m) |", "| --- | --- | --- |"])
    for row in rows:
        lines.append(f"| {row['source_spacing_m']:g} | {row['source_count']} | {row['max_component_error_m']:.9g} |")
    lines.extend(["", "Thresholds are declared before calculation in subsidence/phase4_verification.py. These checks concern numerical consistency of the selected formulation; asymmetry is only qualitative evidence.", "", "![Coordinate decomposition](coordinate_diagram.png)", "", "![Convergence](convergence.png)", "", "![Dip study](dip_profiles.png)", ""])
    (target / "verification.md").write_text("\n".join(lines), encoding="utf-8")
