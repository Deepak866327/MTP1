"""Replayable calibration bundles and frozen held-out comparisons."""

import csv
import hashlib
from pathlib import Path

from matplotlib.figure import Figure

from .calibration import CalibrationResult, parameter_vector
from .config import save_model, save_project
from .phase3_results import _json, _new_directory
from .phase5_results import export_baseline


def _save_attempts(target, attempts):
    _json(target / "optimizer_attempts.json", list(attempts))
    with (target / "objective_trace.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["start_index", "evaluation_including_jacobian", "amplitude_m", "influence_angle_deg", "sum_squared_residual_m2"])
        for attempt in attempts:
            for row in attempt["objective_trace"]:
                writer.writerow([attempt["start_index"], row["evaluation"], row["amplitude_m"], row["influence_angle_deg"], row["sum_squared_residual_m2"]])


def export_calibration_failure(project, model, dataset, settings, failure, output):
    target = Path(output)
    _new_directory(target)
    save_project(project, target / "project.json")
    save_model(model, target / "manual_model.json")
    _json(target / "calibration_settings.json", settings.to_dict())
    (target / "raw_observations.csv").write_bytes(dataset.raw_csv)
    (target / "raw_metadata.json").write_bytes(dataset.raw_metadata)
    _save_attempts(target, failure.attempts)
    summary = {"phase": 6, "status": "failed_no_converged_start", "message": str(failure), "testing_evaluated": False, "fitted_model_selected": False}
    _json(target / "calibration_summary.json", summary)
    return summary


def export_calibration(result: CalibrationResult, output: str | Path) -> dict:
    target = Path(output)
    _new_directory(target)
    save_project(result.project, target / "project.json")
    save_model(result.manual_model, target / "manual_model.json")
    save_model(result.fitted_model, target / "fitted_model.json")
    _json(target / "calibration_settings.json", result.settings.to_dict())
    _save_attempts(target, result.attempts)
    export_baseline(result.project, result.fitted_model, result.fitted, target / "fitted_evaluation")
    export_baseline(result.project, result.manual_model, result.manual, target / "manual_evaluation")
    selected = result.attempts[result.selected_start]
    comparisons = {}
    for line_id, fitted in result.fitted.line_metrics.items():
        manual = result.manual.line_metrics[line_id]
        comparisons[line_id] = {"role": fitted["role"], "manual": manual, "fitted": fitted, "fitted_minus_manual_rmse_m": fitted["rmse_m"] - manual["rmse_m"]}
    dataset = result.fitted.dataset
    summary = {
        "phase": 6, "status": "converged_with_diagnostics", "evidence": dataset.metadata.evidence,
        "manual_model": result.manual_model.to_dict(), "fitted_model": result.fitted_model.to_dict(),
        "calibration_settings": result.settings.to_dict(), "selected_start_index": result.selected_start,
        "selected_fit_sum_squared_residual_m2": selected["sum_squared_residual_m2"],
        "fit_residual_vector_m": result.fitted.residual_m[[s.station_id in set(result.diagnostics["fit_station_ids"]) for s in dataset.stations]].tolist(),
        "diagnostics": result.diagnostics, "line_comparisons": comparisons,
        "manual_role_metrics": result.manual.role_metrics, "fitted_role_metrics": result.fitted.role_metrics,
        "csv_sha256": dataset.csv_sha256, "metadata_sha256": hashlib.sha256(dataset.raw_metadata).hexdigest(),
        "testing_policy": "Models frozen before held-out evaluation. Test observations, reported RMSE and uncertainty columns do not enter fitting, weighting or start selection.",
        "preprocessing": "Declared vertical-sign conversion only; no offsets, exclusions, coordinate changes or data-driven bounds.",
        "exact_original_reproduction_established": False,
        "field_data_evaluated": dataset.metadata.evidence == "field_measurements",
        "accuracy_claim": "Synthetic recovery verifies the inversion workflow only." if dataset.metadata.evidence == "synthetic_verification" else "Held-out metrics describe this dataset and reconstruction; no general accuracy improvement is inferred automatically.",
        "repeated_testing_note": "If test outcomes guide parameter bounds, preprocessing or later revisions, use a new independent evaluation dataset.",
    }
    _json(target / "calibration_summary.json", summary)
    figure = Figure(figsize=(11, 4.5), layout="constrained")
    trace_axis, parameter_axis = figure.subplots(1, 2)
    for attempt in result.attempts:
        trace = attempt["objective_trace"]
        trace_axis.semilogy([r["evaluation"] for r in trace], [max(r["sum_squared_residual_m2"], 1e-30) for r in trace], label=f"Start {attempt['start_index']} ({'converged' if attempt['success'] else 'failed'})")
        start, final = attempt["initial_parameters"], attempt["parameters"]
        parameter_axis.plot([start[0], final[0]], [start[1], final[1]], "o--", label=f"Start {attempt['start_index']}")
    best = parameter_vector(result.fitted_model)
    parameter_axis.plot(best[0], best[1], "k*", markersize=14, label="Selected fit")
    parameter_axis.set(xlim=result.settings.amplitude_bounds_m, ylim=result.settings.influence_angle_bounds_deg, xlabel="Amplitude (m)", ylabel="Influence angle (degrees)", title="Supplied starts and final parameters")
    trace_axis.set(xlabel="Objective evaluation (includes finite differences)", ylabel="Fit SSE (m²); display floor 1e-30", title="Fit-only objective evaluations")
    for axis in (trace_axis, parameter_axis):
        axis.grid(True, alpha=0.25)
        axis.legend(fontsize=8)
    figure.suptitle(f"Phase 6 calibration | {dataset.metadata.evidence}")
    figure.savefig(target / "calibration_diagnostics.png", dpi=160)
    figure.savefig(target / "calibration_diagnostics.svg")
    lines = ["# Phase 6 automatic calibration", "", f"Evidence: **{dataset.metadata.evidence}**. {summary['accuracy_claim']}", "", f"Selected start: {result.selected_start}; fit-only SSE: {selected['sum_squared_residual_m2']:.10g} m².", "", "Amplitude is in metres (flat Smax or inclined p); beta is in degrees. Other solver conventions and geometry remain fixed.", "", "| Parameter | Supplied manual | Fitted | Bounds |", "| --- | --- | --- | --- |"]
    manual = parameter_vector(result.manual_model)
    for name, i, bounds in (("Amplitude (m)", 0, result.settings.amplitude_bounds_m), ("Influence angle (degrees)", 1, result.settings.influence_angle_bounds_deg)):
        lines.append(f"| {name} | {manual[i]:.9g} | {best[i]:.9g} | {bounds} |")
    lines.extend(["", f"Bounds basis: {result.settings.bounds_basis}. {result.settings.bounds_justification}", "", "## Frozen-model comparison", "", "Residual = predicted global Uz - observed canonical Uz. All metrics are unweighted metres.", "", "| Line | Role | N | Manual RMSE | Fitted RMSE | Fitted - manual RMSE | Fitted MAE | Fitted bias |", "| --- | --- | --- | --- | --- | --- | --- | --- |"])
    for name, comparison in comparisons.items():
        f, m = comparison["fitted"], comparison["manual"]
        lines.append(f"| {name} | {f['role']} | {f['count']} | {m['rmse_m']:.9g} | {f['rmse_m']:.9g} | {comparison['fitted_minus_manual_rmse_m']:+.6g} | {f['mae_m']:.6g} | {f['bias_m']:.6g} |")
    d = result.diagnostics
    lines.extend(["", "## Identifiability and starts", "", f"Converged starts: {d['successful_start_count']}/{len(result.attempts)}. Scaled Jacobian rank: {d['scaled_jacobian_rank']}; condition: {d['scaled_jacobian_condition_number']}; sensitivity-column cosine: {d['sensitivity_column_cosine']}.", "", f"Parameter spread across successful starts [m, degrees]: {d['successful_parameter_spread']}.", "", "The Jacobian columns are scaled by the respective declared bound widths. The documented thresholds are diagnostic heuristics, not statistical confidence intervals. Good local conditioning and agreeing starts do not prove global uniqueness.", "", *[f"- {w}" for w in d["warnings"]], "", "![Objective and parameter diagnostics](calibration_diagnostics.png)", "", "## Data and evaluation policy", "", summary["testing_policy"], summary["preprocessing"], summary["repeated_testing_note"], "", "Raw CSV/metadata bytes, station residuals and fit/test plots are in fitted_evaluation and manual_evaluation. Their Phase 5 reports describe evaluation with frozen settings; fitting occurs in this parent Phase 6 run. Both flat and inclined model settings can be replayed using evaluate-stations or the displacement commands.", "", "Exact original-engine reproduction remains unestablished. Synthetic examples are not field validation; surveyed digitization remains approximate. Original inclined-model conventions remain unresolved. The supplied manual model is a comparison baseline, not necessarily the report's original parameter choice.", ""])
    for figure in range(1, len(dataset.metadata.line_roles) + 1):
        lines.extend([f"![Frozen fitted evaluation line {figure}](fitted_evaluation/line_{figure:03d}.png)", ""])
    (target / "calibration_report.md").write_text("\n".join(lines), encoding="utf-8")
    return summary
