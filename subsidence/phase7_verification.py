"""Reproducible synthetic desktop bundles; UI interaction tests live in tests/."""

from pathlib import Path

import numpy as np

from .desktop_plots import field_figure
from .phase3_results import _json, _new_directory
from .workspace import calibrate_document, compute_document, example_document, export_run, open_run, save_document


def export_desktop_verification(output):
    root = Path(output)
    _new_directory(root)
    checks = []

    def add(name, condition):
        checks.append({"name": name, "passed": bool(condition)})

    flat = compute_document(example_document("Synthetic flat"))
    save_document(flat.document, root / "flat_project.json")
    export_run(flat, root / "flat_run.zip")
    restored = open_run(root / "flat_run.zip")
    add("flat_displacement_exact_round_trip", np.array_equal(flat.displacement.displacement_m, restored.displacement.displacement_m))
    add("flat_strain_exact_round_trip", np.array_equal(flat.strain.ex, restored.strain.ex) and np.array_equal(flat.strain.ey, restored.strain.ey))
    add("flat_settings_and_provenance_round_trip", flat.document.to_dict() == restored.document.to_dict())
    line = flat.document.profiles[0]
    add("cached_profile_exact_round_trip", np.array_equal(flat.profile(line).displacement_m, restored.profile(line).displacement_m))
    add("positive_settlement_is_negative_uz", np.array_equal(flat.values("Settlement"), -flat.values("Uz")))
    add("strain_display_units", np.array_equal(flat.values("Ex"), 1000 * flat.strain.ex))
    image = field_figure(restored, "Ex", "RdBu_r")
    norm = image.axes[0].collections[0].norm
    add("strain_scale_centered_zero", norm.vcenter == 0 and norm.vmin == -norm.vmax)
    image.savefig(root / "flat_strain.png", dpi=160)
    image.savefig(root / "flat_strain.svg")
    calibrated = calibrate_document(example_document("Synthetic calibration demo"))
    save_document(calibrated.document, root / "calibrated_project.json")
    export_run(calibrated, root / "calibrated_run.zip")
    restored = open_run(root / "calibrated_run.zip")
    add("calibrated_displacement_exact_round_trip", np.array_equal(calibrated.displacement.displacement_m, restored.displacement.displacement_m))
    add("station_residuals_exact_round_trip", np.array_equal(calibrated.evaluation.residual_m, restored.evaluation.residual_m))
    add("station_metrics_round_trip", calibrated.evaluation.line_metrics == restored.evaluation.line_metrics)
    add("raw_observation_bytes_retained", calibrated.document.observations.raw_csv == restored.document.observations.raw_csv and calibrated.document.observations.raw_metadata == restored.document.observations.raw_metadata)
    add("calibration_settings_retained", calibrated.document.calibration_settings == restored.document.calibration_settings)
    add("synthetic_evidence_preserved", restored.calibration_summary["evidence"] == "synthetic_verification")
    add("test_excluded_from_parameter_selection", restored.calibration_summary["diagnostics"]["testing_used_for_selection"] is False)
    summary = {"phase": 7, "evidence": "synthetic_verification", "passed": all(c["passed"] for c in checks), "checks": checks, "field_validation_established": False, "ui_verification": "Native Tk interaction, background jobs, form editing, import/save/export/open, observation upload, calibration and cached display actions are exercised in tests/test_phase7.py. This command verifies portable numerical bundles without opening a GUI."}
    _json(root / "verification.json", summary)
    lines = ["# Phase 7 desktop bundle verification", "", f"Result: {'PASS' if summary['passed'] else 'FAIL'}; {len(checks)} checks.", "", "All data is synthetic. These results establish software behavior, not field accuracy or original-engine reproduction.", "", "| Check | Result |", "| --- | --- |"]
    for check in checks:
        lines.append(f"| {check['name']} | {'PASS' if check['passed'] else 'FAIL'} |")
    lines.extend(["", "Open flat_run.zip or calibrated_run.zip with the workbench's Open run ZIP button. Reopening uses arrays without running the influence solver; profiles/colors reuse those arrays. Each ZIP includes model/project settings, CSV/NPZ arrays, PNG/SVG figures and a hash manifest. The calibrated ZIP also retains original observation bytes, fit settings, objectives, manual/fitted metrics and held-out reports.", "", summary["ui_verification"], "", "![Synthetic signed strain map](flat_strain.png)", ""])
    (root / "verification.md").write_text("\n".join(lines), encoding="utf-8")
    return summary
