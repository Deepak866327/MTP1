"""Approximate published-curve audit; never supplies invented station coordinates."""

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from .config import _reject_constant, _unique_object
from .evaluation import residual_metrics
from .geometry import ValidationError, finite_number


@dataclass(frozen=True)
class DigitizedLine:
    line_id: str
    role: str
    page: int
    source_image: Path
    pixel_samples: np.ndarray
    observed_distance_m: np.ndarray
    observed_uz_m: np.ndarray
    reported_prediction_distance_m: np.ndarray
    reported_prediction_uz_m: np.ndarray
    comparison_distance_m: np.ndarray
    compared_observed_uz_m: np.ndarray
    compared_reported_uz_m: np.ndarray
    metrics: dict


@dataclass(frozen=True)
class DigitizedReport:
    manifest: dict
    raw_manifest: bytes
    source_root: Path
    lines: tuple[DigitizedLine, ...]


def _array(value, columns, label):
    array = np.asarray(value, dtype=float)
    if array.ndim != 2 or array.shape[1] != columns or len(array) < 2 or not np.all(np.isfinite(array)) or np.any(np.diff(array[:, 0]) <= 0):
        raise ValidationError(f"{label} must be finite rows with {columns} columns and strictly increasing first coordinates.")
    return array


def _checked_hash(path, expected):
    if not isinstance(expected, str) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValidationError(f"Digitization source hash mismatch: {path.name}.")


def _tick_distance(x, ticks):
    # Linear extension up to the neighboring tick interval permits tracing
    # points before/after the outer labeled ticks, not arbitrary extrapolation.
    result = np.interp(x, ticks[:, 0], ticks[:, 1])
    for left, right, selected in ((ticks[0], ticks[1], x < ticks[0, 0]), (ticks[-2], ticks[-1], x > ticks[-1, 0])):
        result[selected] = left[1] + (x[selected] - left[0]) * (right[1] - left[1]) / (right[0] - left[0])
    if np.any(x < 2 * ticks[0, 0] - ticks[1, 0]) or np.any(x > 2 * ticks[-1, 0] - ticks[-2, 0]):
        raise ValidationError("Digitized trace exceeds the calibrated distance-axis range.")
    return result


def load_digitized_report(path: str | Path) -> DigitizedReport:
    path = Path(path)
    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1 or data.get("evidence") != "approximate_digitized_published_curves":
        raise ValidationError("Expected version-1 approximate_digitized_published_curves manifest.")
    try:
        root = (path.parent / data["source_root_relative"]).resolve()
        _checked_hash(root / data["source_pdf"], data["source_pdf_sha256"])
        uncertainty = finite_number(data["vertical_uncertainty_m_assumed"], "digitization uncertainty")
        distance_uncertainty = finite_number(data["distance_uncertainty_m_assumed"], "distance uncertainty")
        spacing = finite_number(data["comparison_spacing_m"], "comparison spacing")
        if uncertainty < 0 or distance_uncertainty < 0 or spacing <= 0:
            raise ValidationError("Digitization uncertainties must be nonnegative and comparison spacing positive.")
        records, names = [], set()
        for line in data["lines"]:
            line_id, role = line["line_id"], line["role"]
            if not isinstance(line_id, str) or not line_id.strip() or line_id in names or role not in ("fit", "test"):
                raise ValidationError("Digitized lines require unique names and fit/test roles.")
            names.add(line_id)
            image = root / line["source_image"]
            _checked_hash(image, line["source_image_sha256"])
            samples = _array(line["samples_px_observed_y_predicted_y"], 3, "Pixel samples")
            top, bottom = _array(line["top_border_px"], 2, "Top border"), _array(line["bottom_border_px"], 2, "Bottom border")
            ticks = _array(line["distance_ticks_px_m"], 2, "Distance ticks")
            if np.any(np.diff(ticks[:, 1]) <= 0):
                raise ValidationError("Distance tick values must increase.")
            x = samples[:, 0]
            if x[0] < max(top[0, 0], bottom[0, 0]) or x[-1] > min(top[-1, 0], bottom[-1, 0]):
                raise ValidationError("Trace samples require plot-border calibration over their complete range.")
            upper, lower = np.interp(x, top[:, 0], top[:, 1]), np.interp(x, bottom[:, 0], bottom[:, 1])
            if np.any(lower <= upper):
                raise ValidationError("Plot bottom must lie below its top in pixel coordinates.")
            axis = line["left_axis_calibration"]
            xr = finite_number(axis["reference_x_px"], "axis x")
            t, b = np.interp(xr, top[:, 0], top[:, 1]), np.interp(xr, bottom[:, 0], bottom[:, 1])
            zero = finite_number(axis["zero_y_px"], "axis zero")
            negative_y = finite_number(axis["negative_tick_y_px"], "axis negative tick")
            negative_value = finite_number(axis["negative_tick_uz_m"], "axis value")
            if b <= t or negative_y <= zero or negative_value >= 0:
                raise ValidationError("Left subsidence axis calibration must run from zero down to negative Uz.")
            v0, v1 = (zero - t) / (b - t), (negative_y - t) / (b - t)
            calibrated = []
            for column in (1, 2):
                v = (samples[:, column] - upper) / (lower - upper)
                if np.any(v < 0) or np.any(v > 1):
                    raise ValidationError("Digitized curve lies outside the calibrated plot borders.")
                uz = (v - v0) * negative_value / (v1 - v0)
                shear = finite_number(line["horizontal_shear_to_bottom_px"], "pixel shear")
                distance = _tick_distance(x + (1 - v) * shear, ticks)
                if np.any(np.diff(distance) <= 0):
                    raise ValidationError("Calibrated trace distance must increase.")
                calibrated.append((distance, uz))
            (od, ou), (pd, pu) = calibrated
            start, stop = max(od[0], pd[0]), min(od[-1], pd[-1])
            count = math.floor(stop / spacing) - math.ceil(start / spacing) + 1
            if not 2 <= count <= 1_000_000:
                raise ValidationError("Digitized common comparison grid must contain 2..1,000,000 samples.")
            common = (math.ceil(start / spacing) + np.arange(count)) * spacing
            observed, predicted = np.interp(common, od, ou), np.interp(common, pd, pu)
            metrics = residual_metrics(observed, predicted)
            reported = finite_number(line["reported_rmse_m"], "reported RMSE")
            if reported < 0:
                raise ValidationError("Reported RMSE cannot be negative.")
            metrics.update({"reported_rmse_m": reported, "rmse_minus_reported_m": metrics["rmse_m"] - reported, "vertical_only_rmse_bound_m": [max(0, metrics["rmse_m"] - 2 * uncertainty), metrics["rmse_m"] + 2 * uncertainty]})
            records.append(DigitizedLine(line_id, role, line["pdf_page"], image, samples, od, ou, pd, pu, common, observed, predicted, metrics))
        if not records or {r.role for r in records} != {"fit", "test"}:
            raise ValidationError("Digitized comparison needs both fit and test published profiles.")
    except (KeyError, TypeError) as exc:
        raise ValidationError(f"Incomplete digitization manifest: {exc}.") from exc
    return DigitizedReport(data, raw, root, tuple(records))
