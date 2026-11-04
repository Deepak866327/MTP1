"""Deterministic synthetic station-pipeline verification with known residuals."""

import csv
import json
import math
from pathlib import Path

import numpy as np

from .config import FlatModel
from .evaluation import evaluate_stations
from .observations import load_observations
from .phase3_results import _json, _new_directory
from .phase5_results import export_baseline
from .verification import verification_project


METRIC_ATOL_M = 1e-12


def synthetic_metadata():
    return {
        "schema_version": 1, "units": {"length": "m"}, "name": "Synthetic known-residual station check",
        "evidence": "synthetic_verification", "vertical_sign": "settlement_positive",
        "coordinate_reference": "Constructed global Cartesian test coordinates in metres; no surveyed mine stations.",
        "vertical_datum": "Synthetic zero surface datum; settlement input deliberately positive.",
        "measurement_stage": "Synthetic final-stage verification fixture, not a monitoring date.",
        "provenance": "Explicitly constructed values 1,2,3,4 m against a zero-amplitude model for exact metric checks.",
        "line_roles": {"FIT_SYNTHETIC": "fit", "TEST_SYNTHETIC": "test"},
    }


def export_baseline_verification(output: str | Path) -> dict:
    target = Path(output)
    _new_directory(target)
    csv_path, metadata_path = target / "input_observations.csv", target / "input_metadata.json"
    rows = [
        ["SYNTHETIC_F1", "FIT_SYNTHETIC", -31.5, 7.25, 1, 0],
        ["SYNTHETIC_F2", "FIT_SYNTHETIC", 17.75, -3.5, 2, 50],
        ["SYNTHETIC_T1", "TEST_SYNTHETIC", -7.2, 41.3, 3, 0],
        ["SYNTHETIC_T2", "TEST_SYNTHETIC", 59.8, 13.7, 4, 75],
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["station_id", "line_id", "x_m", "y_m", "uz_observed_m", "distance_m"])
        writer.writerows(rows)
    _json(metadata_path, synthetic_metadata())
    data = load_observations(csv_path, metadata_path)
    project, model = verification_project(), FlatModel(0, 20)
    result = evaluate_stations(project, model, data)
    export_baseline(project, model, result, target / "synthetic_case")
    checks = []

    def add(name, value):
        checks.append({"name": name, "passed": bool(value <= METRIC_ATOL_M), "max_absolute_error_m": float(value), "absolute_tolerance_m": METRIC_ATOL_M})

    for role, values in (("fit", np.array([1.0, 2.0])), ("test", np.array([3.0, 4.0]))):
        metrics = result.role_metrics[role]
        add(f"{role}_rmse", abs(metrics["rmse_m"] - math.sqrt(float(np.mean(values**2)))))
        add(f"{role}_mae", abs(metrics["mae_m"] - float(values.mean())))
        add(f"{role}_bias", abs(metrics["bias_m"] - float(values.mean())))
    add("declared_sign_conversion", np.max(np.abs(np.array([s.uz_observed_m for s in data.stations]) + np.arange(1, 5))))
    add("zero_amplitude_predictions", np.max(np.abs(result.prediction.displacement_m)))
    add("exact_supplied_coordinates", np.max(np.abs(result.prediction.xyz_m[:, :2] - np.array([r[2:4] for r in rows]))))
    summary = {"phase": 5, "evidence": "synthetic_station_pipeline_verification", "passed": all(c["passed"] for c in checks), "checks": checks, "role_metrics": result.role_metrics, "field_validation_established": False}
    _json(target / "verification.json", summary)
    lines = ["# Phase 5 station-pipeline verification", "", f"Overall result: {'PASS' if summary['passed'] else 'FAIL'}.", "", "Synthetic positive-settlement inputs 1,2,3,4 m are compared with a zero-amplitude model. These are not Adriyala observations and do not validate field accuracy.", "", "| Check | Result | Absolute error (m) | Tolerance (m) |", "| --- | --- | --- | --- |"]
    for check in checks:
        lines.append(f"| {check['name']} | {'PASS' if check['passed'] else 'FAIL'} | {check['max_absolute_error_m']} | {check['absolute_tolerance_m']} |")
    lines.extend(["", "The synthetic_case subdirectory retains exact input bytes, settings, station predictions/residuals, grouped metrics and plots. Both groups use the same fixed model; no fitting occurs.", ""])
    (target / "verification.md").write_text("\n".join(lines), encoding="utf-8")
    return summary
