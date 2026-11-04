"""Repeatable synthetic Phase 2 checks with predefined numerical tolerances."""

import csv
from dataclasses import replace
import json
import math
from pathlib import Path

import numpy as np

from .config import FlatModel, Project, Spacing, save_flat_model, save_project
from .geometry import Rectangle, SeamPlane, ValidationError
from .plotting import save_convergence_plot
from .reference import analytical_flat_displacement
from .solver import solve_flat


# Set before evaluating the implementation. These are synthetic numerical
# tolerances, unrelated to reported field RMSE or geological uncertainty.
SYMMETRY_ATOL_M = 1e-12
LINEARITY_ATOL_M = 1e-12
CHUNK_ATOL_M = 1e-12
FAR_FIELD_ATOL_M = 1e-12
FINE_MESH_ATOL_M = 2e-4
SINGLE_CELL_ATOL_M = 1e-15
CONVERGENCE_SPACINGS_M = (40.0, 20.0, 10.0, 5.0, 2.5)


def verification_project() -> Project:
    return Project(
        name="Phase 2 synthetic flat-panel verification", evidence="synthetic_geometry",
        field=Rectangle(-500, 500, -400, 400), seam=SeamPlane((0, 0, -400), (0, 0, 1)),
        extraction_rectangles=(Rectangle(-200, 200, -100, 100),),
        source_mesh=Spacing(10, 10), surface_grid=Spacing(20, 20),
        provenance={"description": "Synthetic numerical benchmark; contains no monitoring observations."},
    )


def run_flat_verification() -> dict:
    project, model = verification_project(), FlatModel(1, 20)
    x, y = np.meshgrid(np.linspace(-300, 300, 7), np.linspace(-200, 200, 5), indexing="xy")
    points = np.stack([x, y, np.zeros_like(x)], axis=-1)
    base = solve_flat(project, model, points)
    checks = []

    def add(name, value, tolerance):
        checks.append({"name": name, "passed": bool(value <= tolerance), "max_absolute_error_m": float(value), "absolute_tolerance_m": tolerance})

    empty = solve_flat(replace(project, extraction_rectangles=()), model, points)
    add("zero_extraction", np.max(np.abs(empty.displacement_m)), 0.0)
    zero = solve_flat(project, FlatModel(0, 20), points)
    add("zero_amplitude", np.max(np.abs(zero.displacement_m)), 0.0)
    center = solve_flat(project, model, [[0, 0, 0]])
    add("center_horizontal_cancellation", np.max(np.abs(center.displacement_m[:, :2])), SYMMETRY_ATOL_M)
    x_mirror = base.displacement_m[:, ::-1] * [-1, 1, 1]
    y_mirror = base.displacement_m[::-1, :] * [1, -1, 1]
    add("x_reflection", np.max(np.abs(base.displacement_m - x_mirror)), SYMMETRY_ATOL_M)
    add("y_reflection", np.max(np.abs(base.displacement_m - y_mirror)), SYMMETRY_ATOL_M)
    doubled = solve_flat(project, FlatModel(2, 20), points)
    add("amplitude_linearity", np.max(np.abs(doubled.displacement_m - 2 * base.displacement_m)), LINEARITY_ATOL_M)
    far = solve_flat(project, model, [[2000, 2000, 0]])
    add("far_field_decay", np.max(np.abs(far.displacement_m)), FAR_FIELD_ATOL_M)
    blocked = solve_flat(project, model, points, observation_chunk_size=3, source_chunk_size=37)
    add("chunk_equivalence", np.max(np.abs(blocked.displacement_m - base.displacement_m)), CHUNK_ATOL_M)

    # One 2x2 m midpoint source, H=100 m, beta=45 degrees, Smax=2 m.
    tiny = replace(project, seam=SeamPlane((0, 0, -100), (0, 0, 1)), extraction_rectangles=(Rectangle(-1, 1, -1, 1),), source_mesh=Spacing(2, 2))
    tiny_points = np.array([[0, 0, 0], [100, 0, 0]], dtype=float)
    tiny_result = solve_flat(tiny, FlatModel(2, 45), tiny_points)
    w = 2 * 4 / 100**2
    expected = np.array([[0, 0, -w], [-w * math.exp(-math.pi), 0, -w * math.exp(-math.pi)]])
    add("transparent_single_cell", np.max(np.abs(tiny_result.displacement_m - expected)), SINGLE_CELL_ATOL_M)

    exact = analytical_flat_displacement(project, model, points)
    rows = []
    for spacing in CONVERGENCE_SPACINGS_M:
        refined = replace(project, source_mesh=Spacing(spacing, spacing))
        result = solve_flat(refined, model, points)
        error = np.abs(result.displacement_m - exact)
        rows.append({
            "source_spacing_m": spacing,
            "source_count": len(result.sources.xyz_m),
            "max_ux_error_m": float(error[..., 0].max()),
            "max_uy_error_m": float(error[..., 1].max()),
            "max_uz_error_m": float(error[..., 2].max()),
            "max_component_error_m": float(error.max()),
        })
    decreasing = all(b["max_component_error_m"] < a["max_component_error_m"] for a, b in zip(rows, rows[1:]))
    checks.append({"name": "mesh_error_strictly_decreases", "passed": decreasing})
    add("finest_mesh_analytical_agreement", rows[-1]["max_component_error_m"], FINE_MESH_ATOL_M)
    return {
        "phase": 2,
        "evidence": "synthetic_numerical_verification_not_field_validation",
        "passed": all(check["passed"] for check in checks),
        "benchmark_project": project.to_dict(),
        "model": model.to_dict(),
        "checks": checks,
        "convergence": rows,
        "verification_point_count": int(x.size),
        "analytical_center_displacement_m": analytical_flat_displacement(project, model, [[0, 0, 0]])[0].tolist(),
        "implementation": {"python_version": base.metadata["python_version"], "numpy_version": np.__version__},
    }


def export_flat_verification(report: dict, output: str | Path) -> None:
    target = Path(output)
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValidationError(f"Output directory must be empty: {target}. Choose a new output path.")
    target.mkdir(parents=True, exist_ok=True)
    (target / "verification.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    save_project(Project.from_dict(report["benchmark_project"]), target / "project.json")
    save_flat_model(FlatModel.from_dict(report["model"]), target / "model.json")
    rows = report["convergence"]
    with (target / "convergence.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "# Phase 2 flat-seam numerical verification", "",
        f"Overall result: {'PASS' if report['passed'] else 'FAIL'}.", "",
        "Synthetic verification only. No original field result or accuracy improvement is claimed.", "",
        "Benchmark: 400 x 200 m panel at depth 400 m, Smax=1 m, beta=20 degrees; full Gaussian support.",
        "The analytical reference integrates the Gaussian and its first moments over rectangles, without source meshing.", "",
        "## Checks", "", "| Check | Result | Absolute error (m) | Tolerance (m) |", "| --- | --- | --- | --- |",
    ]
    for check in report["checks"]:
        error, tolerance = check.get("max_absolute_error_m"), check.get("absolute_tolerance_m")
        lines.append(f"| {check['name']} | {'PASS' if check['passed'] else 'FAIL'} | {error if error is not None else 'n/a'} | {tolerance if tolerance is not None else 'n/a'} |")
    lines.extend(["", "## Source-mesh convergence", "", f"All three components compared at the same {report['verification_point_count']} observation coordinates.", "", "| Spacing (m) | Sources | Maximum component error (m) |", "| --- | --- | --- |"])
    for row in rows:
        lines.append(f"| {row['source_spacing_m']:g} | {row['source_count']} | {row['max_component_error_m']:.9g} |")
    lines.extend(["", "Tolerances are fixed in subsidence/verification.py before calculation. They are numerical tolerances for this benchmark; other depths, angles and meshes require their own convergence checks.", "", "![Convergence plot](convergence.png)", ""])
    (target / "verification.md").write_text("\n".join(lines), encoding="utf-8")
    save_convergence_plot(rows, target)
