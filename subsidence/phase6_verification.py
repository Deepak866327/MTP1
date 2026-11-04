"""Independent-reference synthetic calibration checks; no mine observations."""

import csv
from dataclasses import replace
from pathlib import Path

import numpy as np

from .calibration import CalibrationSettings, calibrate_stations, parameter_vector
from .config import FlatModel, InclinedModel, save_model, save_project
from .geometry import SeamPlane
from .inclined import solve_inclined
from .inclined_reference import quadrature_inclined_displacement
from .observations import load_observations
from .phase3_results import _json, _new_directory
from .phase5_verification import synthetic_metadata
from .phase6_results import export_calibration
from .reference import analytical_flat_displacement
from .solver import solve_flat
from .verification import verification_project


# Fixed before running inversion: mesh error is allowed in independent recovery.
AMPLITUDE_ATOL_M = 0.002
ANGLE_ATOL_DEG = 0.1
HELD_OUT_RMSE_ATOL_M = 0.001
DISCRETE_AMPLITUDE_ATOL_M = 1e-7
DISCRETE_ANGLE_ATOL_DEG = 1e-5


def synthetic_settings():
    return CalibrationSettings(
        (0, 3.5), (10, 40), ((0.4, 12), (1.3, 20), (2.8, 36)),
        "synthetic_demonstration",
        "Constructed demonstration: amplitude 0..3.5 m assumes an illustrative 3.5 m extraction height; beta 10..40 degrees deliberately brackets known synthetic truth. These are not established Adriyala bounds.",
    )


def write_synthetic_inputs(output, *, inclined=False, independent=True):
    target = Path(output)
    _new_directory(target)
    project = verification_project()
    if inclined:
        dip = np.deg2rad(10)
        project = replace(project, name="Synthetic 10-degree calibration benchmark", seam=SeamPlane((0, 0, -400), (0, np.sin(dip), np.cos(dip))))
    truth = InclinedModel(1.2, 23) if inclined else FlatModel(1.2, 23)
    manual = InclinedModel(1.3, 20) if inclined else FlatModel(1.3, 20)
    fit_y, test_y = np.linspace(-300, 300, 31), np.linspace(-280, 280, 23)
    points = np.array([[-35.25, y, 0] for y in fit_y] + [[125.75, y, 0] for y in test_y])
    if independent:
        observed = (quadrature_inclined_displacement(project, truth, points) if inclined else analytical_flat_displacement(project, truth, points))[:, 2]
        generator = "Independent global Gauss-Legendre rectangle integration (order 48)." if inclined else "Independent analytical rectangle integral."
    else:
        observed = (solve_inclined if inclined else solve_flat)(project, truth, points).uz_m
        generator = "Discrete forward/inverse consistency using the production source mesh."
    metadata = synthetic_metadata() | {
        "name": f"Synthetic {'inclined' if inclined else 'flat'} known-parameter recovery",
        "vertical_sign": "up_positive", "vertical_datum": "Constructed global z=0 surface, metres upward.",
        "provenance": generator + " Known amplitude 1.2 m and beta 23 degrees; no noise or mine observations.",
    }
    csv_path = target / "observations.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["station_id", "line_id", "x_m", "y_m", "uz_observed_m", "distance_m"])
        for i, (point, uz) in enumerate(zip(points, observed)):
            fitting = i < len(fit_y)
            line = "FIT_SYNTHETIC" if fitting else "TEST_SYNTHETIC"
            distance = point[1] - (fit_y[0] if fitting else test_y[0])
            writer.writerow([f"SYN_{'F' if fitting else 'T'}{i + 1:03d}", line, *point[:2], uz, distance])
    _json(target / "metadata.json", metadata)
    _json(target / "calibration_settings.json", synthetic_settings().to_dict())
    save_project(project, target / "project.json")
    save_model(truth, target / "truth_model.json")
    save_model(manual, target / "manual_model.json")
    return project, truth, manual, load_observations(csv_path, target / "metadata.json")


def export_calibration_verification(output):
    target = Path(output)
    _new_directory(target)
    checks, cases = [], []

    def add(name, value, tolerance, unit):
        checks.append({"name": name, "passed": bool(value <= tolerance), "absolute_error": float(value), "tolerance": tolerance, "unit": unit})

    for name, inclined in (("flat_independent", False), ("inclined_independent", True), ("flat_discrete", False)):
        project, truth, manual, data = write_synthetic_inputs(target / f"{name}_inputs", inclined=inclined, independent=name != "flat_discrete")
        result = calibrate_stations(project, manual, data, synthetic_settings())
        summary = export_calibration(result, target / name)
        errors = np.abs(parameter_vector(result.fitted_model) - parameter_vector(truth))
        add(f"{name}_amplitude_recovery", errors[0], DISCRETE_AMPLITUDE_ATOL_M if name == "flat_discrete" else AMPLITUDE_ATOL_M, "m")
        add(f"{name}_angle_recovery", errors[1], DISCRETE_ANGLE_ATOL_DEG if name == "flat_discrete" else ANGLE_ATOL_DEG, "degrees")
        add(f"{name}_held_out_rmse", result.fitted.role_metrics["test"]["rmse_m"], HELD_OUT_RMSE_ATOL_M, "m")
        add(f"{name}_start_spread", max(np.array(result.diagnostics["successful_parameter_spread"]) / [3.5, 30]), 1e-6, "fraction of bound width")
        add(f"{name}_all_starts_converged", len(result.attempts) - result.diagnostics["successful_start_count"], 0, "count")
        add(f"{name}_jacobian_full_rank", 2 - result.diagnostics["scaled_jacobian_rank"], 0, "rank deficit")
        cases.append({"name": name, "truth": truth.to_dict(), "fitted": result.fitted_model.to_dict(), "fit_rmse_m": summary["fitted_role_metrics"]["fit"]["rmse_m"], "held_out_rmse_m": summary["fitted_role_metrics"]["test"]["rmse_m"], "reference": data.metadata.provenance})
    summary = {"phase": 6, "evidence": "synthetic_verification", "passed": all(c["passed"] for c in checks), "checks": checks, "cases": cases, "field_validation_established": False, "tolerance_basis": "Independent recovery permits midpoint source discretization bias at 10 m spacing, consistent with prior convergence studies; discrete consistency uses tighter optimizer tolerances. These fixed synthetic tolerances are not a general calibration accuracy guarantee."}
    _json(target / "verification.json", summary)
    lines = ["# Phase 6 synthetic calibration verification", "", f"Overall result: {'PASS' if summary['passed'] else 'FAIL'}.", "", "Truth: amplitude 1.2 m, beta 23 degrees. Fitting uses 31 stations along x=-35.25 m; the 23 stations at x=125.75 m are held out. Flat and 10-degree inclined cases are evaluated against independent integrals. A separate discrete flat check verifies optimizer consistency.", "", summary["tolerance_basis"], "", "| Check | Result | Error | Tolerance | Unit |", "| --- | --- | --- | --- | --- |"]
    for c in checks:
        lines.append(f"| {c['name']} | {'PASS' if c['passed'] else 'FAIL'} | {c['absolute_error']:.8g} | {c['tolerance']} | {c['unit']} |")
    lines.extend(["", "These checks use constructed data and demonstrate software behavior only. They do not reproduce the Adriyala RMSE or establish improved mine-prediction accuracy. Each case includes replayable inputs, settings, optimizer traces and frozen fit/test plots.", ""])
    (target / "verification.md").write_text("\n".join(lines), encoding="utf-8")
    return summary
