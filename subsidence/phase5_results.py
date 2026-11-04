"""Station comparison bundles and clearly labeled published-curve digitization."""

import copy
import csv
import hashlib
import json
from pathlib import Path
import shutil

from matplotlib.figure import Figure
from matplotlib.image import imread
import numpy as np

from .config import Model, Project, save_model, save_project
from .digitization import DigitizedReport
from .evaluation import BaselineResult
from .geometry import ValidationError
from .phase3_results import _json, _new_directory


def _comparison_figure(x, observed, predicted, path, *, title, xlabel, labels, uncertainty=None, station_labels=None):
    figure = Figure(figsize=(9, 6), layout="constrained")
    main, residual = figure.subplots(2, 1, sharex=True, gridspec_kw={"height_ratios": [2, 1]})
    main.plot(x, observed, "o-", markersize=3, label=labels[0])
    main.plot(x, predicted, "s-", markersize=3, label=labels[1])
    if uncertainty is not None:
        main.fill_between(x, observed - uncertainty, observed + uncertainty, alpha=0.15)
        main.fill_between(x, predicted - uncertainty, predicted + uncertainty, alpha=0.15, label=f"Assumed reading bounds ±{uncertainty:g} m")
    main.set(ylabel="Uz (m), negative downward")
    main.legend(fontsize=8)
    residual.plot(x, predicted - observed, "o-", markersize=3)
    residual.axhline(0, color="#555555", linewidth=0.8)
    residual.set(xlabel=xlabel, ylabel="Prediction − observed (m)")
    if station_labels is not None:
        residual.set_xticks(x, station_labels, rotation=75, fontsize=8)
    for axis in (main, residual):
        axis.grid(True, alpha=0.25)
    figure.suptitle(title, fontsize=11)
    figure.savefig(path.with_suffix(".png"), dpi=160)
    figure.savefig(path.with_suffix(".svg"))


def export_baseline(project: Project, model: Model, result: BaselineResult, output: str | Path) -> dict:
    if result.prediction.metadata["project"] != project.to_dict() or result.prediction.metadata["settings"] != model.to_dict():
        raise ValidationError("Station results differ from the supplied project/model settings.")
    target = Path(output)
    _new_directory(target)
    dataset = result.dataset
    save_project(project, target / "project.json")
    save_model(model, target / "model.json")
    (target / "raw_observations.csv").write_bytes(dataset.raw_csv)
    (target / "raw_metadata.json").write_bytes(dataset.raw_metadata)
    _json(target / "observation_metadata.json", dataset.metadata.to_dict())
    with (target / "station_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["station_id", "line_id", "role", "x_m", "y_m", "distance_m", "uz_input_m", "uz_observed_m", "ux_predicted_m", "uy_predicted_m", "uz_predicted_m", "residual_m", "uncertainty_m", "measurement_stage", "evidence"])
        for i, station in enumerate(dataset.stations):
            writer.writerow([station.station_id, station.line_id, dataset.metadata.line_roles[station.line_id], station.x_m, station.y_m, station.distance_m, station.uz_input_m, station.uz_observed_m, *result.prediction.displacement_m[i], result.residual_m[i], station.uncertainty_m, dataset.metadata.measurement_stage, dataset.metadata.evidence])
    np.savez_compressed(target / "station_predictions.npz", xyz_m=result.prediction.xyz_m, displacement_m=result.prediction.displacement_m, uz_observed_m=np.array([s.uz_observed_m for s in dataset.stations]), residual_m=result.residual_m)
    figures = []
    for index, (line_id, role) in enumerate(dataset.metadata.line_roles.items(), start=1):
        indices = np.array([i for i, station in enumerate(dataset.stations) if station.line_id == line_id])
        stations = [dataset.stations[i] for i in indices]
        if stations[0].distance_m is not None:
            order = np.argsort([s.distance_m for s in stations])
            indices = indices[order]
            x = np.array([dataset.stations[i].distance_m for i in indices])
            xlabel, station_labels = "Supplied distance along monitoring line (m)", None
        else:
            x = np.arange(len(indices))
            xlabel, station_labels = "Station (original CSV order)", [s.station_id for s in stations]
        observed = np.array([dataset.stations[i].uz_observed_m for i in indices])
        stem = f"line_{index:03d}"
        _comparison_figure(x, observed, result.prediction.uz_m[indices], target / stem, title=f"{dataset.metadata.name}: {line_id} ({role})\n{dataset.metadata.evidence} | frozen model settings | {dataset.metadata.measurement_stage}", xlabel=xlabel, labels=("Observed Uz (declared sign converted)", "Rebuilt model at station coordinates"), station_labels=station_labels)
        figures.append({"line_id": line_id, "role": role, "file_stem": stem, "abscissa": "supplied_distance_m" if stations[0].distance_m is not None else "station_id_input_order"})
    status = {"field_measurements": "field_station_comparison_with_reconstruction", "digitized_with_survey_coordinates": "approximate_digitized_station_comparison", "synthetic_verification": "synthetic_station_pipeline_verification"}[dataset.metadata.evidence]
    summary = {
        "phase": 5, "status": status, "evidence": dataset.metadata.evidence,
        "metadata": dataset.metadata.to_dict(), "model_settings": model.to_dict(),
        "station_count": len(dataset.stations), "line_metrics": result.line_metrics, "role_metrics": result.role_metrics,
        "residual_convention": "predicted global Uz - canonical observed global Uz, metres",
        "coordinate_evaluation": "Direct solver at supplied station x/y and configured surface elevation; no grid snapping or invented survey transform.",
        "preprocessing": "Declared vertical-sign conversion only; no datum shift, outlier exclusion, weighting, or parameter fitting.",
        "parameters_fitted_in_this_run": False, "exact_original_reproduction_established": False,
        "original_reproduction_note": "Published RMSE differences are descriptive. Original model conventions, observations and preprocessing must match before exact reproduction can be claimed.",
        "csv_sha256": dataset.csv_sha256, "metadata_sha256": hashlib.sha256(dataset.raw_metadata).hexdigest(),
        "solver": result.prediction.metadata, "figures": figures,
    }
    _json(target / "baseline_summary.json", summary)
    lines = ["# Phase 5 fixed-parameter station comparison", "", f"Evidence: **{dataset.metadata.evidence}**. Status: {status}.", "", "Predictions use the supplied station coordinates with the same frozen model for fit and test groups. No parameters were fitted in this run.", "", f"Measurement stage: {dataset.metadata.measurement_stage}.", f"Coordinate reference: {dataset.metadata.coordinate_reference}.", f"Vertical datum: {dataset.metadata.vertical_datum}.", "", "Residual = predicted global Uz minus observed global Uz. Metrics are unweighted and in metres.", "", "| Line | Role | Count | RMSE | MAE | Bias | Source-reported RMSE | Difference from reported |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for name, metrics in result.line_metrics.items():
        lines.append(f"| {name} | {metrics['role']} | {metrics['count']} | {metrics['rmse_m']:.6g} | {metrics['mae_m']:.6g} | {metrics['bias_m']:.6g} | {metrics['reported_rmse_m']} | {metrics['rmse_minus_reported_m']} |")
    lines.extend(["", "## Evidence limits", "", "Exact original-engine/RMSE reproduction is not established by this output. Synthetic or digitized input must not be described as raw field validation. Current inclined predictions use the explicitly documented reconstruction conventions. Original CSV and metadata bytes are preserved for review.", ""])
    for figure in figures:
        lines.extend([f"![{figure['line_id']}]({figure['file_stem']}.png)", ""])
    (target / "baseline_report.md").write_text("\n".join(lines), encoding="utf-8")
    return summary


def export_digitized_report(report: DigitizedReport, output: str | Path) -> dict:
    target = Path(output)
    _new_directory(target)
    source_dir = target / "sources"
    source_dir.mkdir()
    manifest = copy.deepcopy(report.manifest)
    manifest["source_root_relative"] = "."
    pdf_target = source_dir / "MTP_1.pdf"
    shutil.copyfile(report.source_root / report.manifest["source_pdf"], pdf_target)
    manifest["source_pdf"] = "sources/MTP_1.pdf"
    for line in manifest["lines"]:
        destination = source_dir / f"mtp1_{line['pdf_page']}.png"
        shutil.copyfile(report.source_root / line["source_image"], destination)
        line["source_image"] = f"sources/{destination.name}"
    _json(target / "digitization.json", manifest)
    (target / "original_digitization_manifest.json").write_bytes(report.raw_manifest)
    uncertainty = report.manifest["vertical_uncertainty_m_assumed"]
    with (target / "digitized_comparison.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["line_id", "role", "pdf_page", "distance_m", "observed_curve_digitized_uz_m", "reported_model_curve_digitized_uz_m", "residual_m", "vertical_reading_bound_m_assumed", "distance_reading_bound_m_assumed", "evidence"])
        for line in report.lines:
            for x, observed, predicted in zip(line.comparison_distance_m, line.compared_observed_uz_m, line.compared_reported_uz_m):
                writer.writerow([line.line_id, line.role, line.page, x, observed, predicted, predicted - observed, uncertainty, report.manifest["distance_uncertainty_m_assumed"], "approximate_digitized_published_curves"])
    with (target / "digitized_trace_points.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["line_id", "trace_sample_index", "image_x_px", "observed_y_px", "reported_model_y_px", "observed_distance_m", "observed_digitized_uz_m", "reported_model_distance_m", "reported_model_digitized_uz_m"])
        for line in report.lines:
            for i, pixels in enumerate(line.pixel_samples):
                writer.writerow([line.line_id, i, *pixels, line.observed_distance_m[i], line.observed_uz_m[i], line.reported_prediction_distance_m[i], line.reported_prediction_uz_m[i]])
    records = []
    for index, line in enumerate(report.lines, start=1):
        stem = f"published_line_{index:03d}"
        _comparison_figure(line.comparison_distance_m, line.compared_observed_uz_m, line.compared_reported_uz_m, target / stem, title=f"{line.line_id} ({line.role} in source), MTP PDF p.{line.page}\nApproximate digitized published curves; rebuilt solver not evaluated", xlabel="Digitized distance along printed line (m); no global station coordinates inferred", labels=("Published mine curve, digitized", "Published fitted/predicted curve, digitized"), uncertainty=uncertainty)
        figure = Figure(figsize=(11, 5), layout="constrained")
        axis = figure.subplots()
        image = imread(line.source_image)
        axis.imshow(image)
        axis.plot(line.pixel_samples[:, 0], line.pixel_samples[:, 1], "o", markersize=4, markerfacecolor="none", color="red", label="Picked mine-curve pixels")
        axis.plot(line.pixel_samples[:, 0], line.pixel_samples[:, 2], "s", markersize=4, markerfacecolor="none", color="blue", label="Picked reported-model pixels")
        original = report.manifest["lines"][index - 1]
        top, bottom = np.array(original["top_border_px"]), np.array(original["bottom_border_px"])
        axis.plot(top[:, 0], top[:, 1], "--", color="orange", linewidth=1)
        axis.plot(bottom[:, 0], bottom[:, 1], "--", color="orange", linewidth=1, label="Approximate plot-border calibration")
        axis.set(xlim=(top[:, 0].min() - 55, top[:, 0].max() + 75), ylim=(bottom[:, 1].max() + 45, top[:, 1].min() - 20), xlabel="Original page image x (pixels)", ylabel="Original page image y (pixels)", title=f"Manual trace audit: PDF p.{line.page}, {line.line_id}; strain curve excluded")
        axis.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=8)
        figure.savefig(target / f"{stem}_pixel_audit.png", dpi=160)
        figure.savefig(target / f"{stem}_pixel_audit.svg")
        records.append({"line_id": line.line_id, "role": line.role, "pdf_page": line.page, "trace_point_count": len(line.pixel_samples), "comparison_point_count": len(line.comparison_distance_m), "comparison_distance_range_m": [float(line.comparison_distance_m[0]), float(line.comparison_distance_m[-1])], "file_stem": stem, **line.metrics})
    summary = {
        "phase": 5, "status": "approximate_published_curve_audit_exact_reproduction_incomplete",
        "evidence": "approximate_digitized_published_curves", "lines": records,
        "comparison_spacing_m": report.manifest["comparison_spacing_m"],
        "vertical_uncertainty_m_assumed": uncertainty, "distance_uncertainty_m_assumed": report.manifest["distance_uncertainty_m_assumed"],
        "uncertainty_note": "Vertical-only RMSE ranges use ±2 times the assumed per-curve reading bound. They are not confidence intervals and omit distance, calibration and sparse-tracing uncertainty.",
        "source": {"pdf": report.manifest["source_pdf"], "sha256": report.manifest["source_pdf_sha256"], "reported_metrics_source": report.manifest["reported_metrics_source"]},
        "rebuilt_engine_station_comparison_completed": False, "exact_original_reproduction_established": False,
        "missing_inputs": ["Global monitoring-station coordinates or independently surveyed line transforms", "Original measured Uz table and measurement stage", "Vertical datum/sign and survey origin/orientation metadata", "Confirmation of original inclined-model conventions"],
        "limitations": report.manifest["limitations"],
    }
    _json(target / "audit_summary.json", summary)
    lines = ["# Phase 5 Adriyala: approximate published-curve audit", "", "**Exact baseline reproduction remains incomplete.** This compares digitized curves already printed in the source, not new solver predictions at monitoring stations.", "", "The scans supply distance profiles but no reliable global station coordinates. No station coordinates, station IDs or measured values have been invented. The right-axis estimated-strain curve is excluded.", "", "| Source line | Role | Comparison samples | Approximate trace RMSE (m) | Source-reported RMSE (m) | Difference (m) |", "| --- | --- | --- | --- | --- | --- |"]
    for line in records:
        lines.append(f"| {line['line_id']} | {line['role']} | {line['comparison_point_count']} | {line['rmse_m']:.3f} | {line['reported_rmse_m']:.2f} | {line['rmse_minus_reported_m']:+.3f} |")
    lines.extend(["", "Comparison samples lie on a common 10 m digitized distance grid within both traces' overlap. They are not original monitoring stations. Raw picked pixels, curved-border calibration, source hashes and source-page copies are retained.", "", f"Assumed reading bounds are ±{uncertainty:g} m vertically per curve and ±{report.manifest['distance_uncertainty_m_assumed']:g} m in distance. Vertical-only RMSE ranges in JSON are diagnostic bounds, not confidence intervals; distance, scan calibration and sparse tracing add uncertainty. Agreement with a rounded source value is not exact reproduction.", "", "## Remaining evidence", "", *[f"- {item}" for item in summary["missing_inputs"]], "", "The implemented evaluate-stations workflow is ready for supplied coordinate/Uz CSV plus provenance metadata. It uses fixed p=1.3 m/beta=20 degrees when paired with the Adriyala model file, evaluates exact station coordinates, exports residuals, and leaves fit/test parameters unchanged.", ""])
    for line in records:
        lines.extend([f"![{line['line_id']} digitized comparison]({line['file_stem']}.png)", "", f"![{line['line_id']} source-pixel audit]({line['file_stem']}_pixel_audit.png)", ""])
    (target / "baseline_report.md").write_text("\n".join(lines), encoding="utf-8")
    return summary
