"""Fixed-parameter predictions and residual metrics at actual station coordinates."""

from dataclasses import dataclass

import numpy as np

from .config import InclinedModel, Model, Project
from .geometry import ValidationError
from .inclined import solve_inclined
from .observations import ObservationDataset
from .solver import DisplacementResult, solve_flat


def residual_metrics(observed, predicted) -> dict:
    observed, predicted = np.asarray(observed, dtype=float), np.asarray(predicted, dtype=float)
    if observed.ndim != 1 or not len(observed) or observed.shape != predicted.shape or not np.all(np.isfinite(observed)) or not np.all(np.isfinite(predicted)):
        raise ValidationError("Metrics require matching nonempty finite one-dimensional observed/predicted arrays.")
    with np.errstate(over="raise", invalid="raise"):
        try:
            error = predicted - observed
            rmse = float(np.sqrt(np.mean(error**2)))
            mae, bias = float(np.mean(np.abs(error))), float(np.mean(error))
        except FloatingPointError as exc:
            raise ValidationError("Residual metrics exceed numerical range.") from exc
    return {"count": len(error), "rmse_m": rmse, "mae_m": mae, "bias_m": bias, "observed_min_uz_m": float(observed.min()), "predicted_min_uz_m": float(predicted.min())}


@dataclass(frozen=True)
class BaselineResult:
    dataset: ObservationDataset
    prediction: DisplacementResult
    residual_m: np.ndarray
    line_metrics: dict
    role_metrics: dict


def evaluate_stations(project: Project, model: Model, dataset: ObservationDataset) -> BaselineResult:
    coordinates = np.array([[r.x_m, r.y_m, project.surface_elevation_m] for r in dataset.stations])
    # One call with frozen settings for both groups. This phase never fits
    # parameters, selects outliers, changes the datum, or snaps to a plot grid.
    solver = solve_inclined if isinstance(model, InclinedModel) else solve_flat
    prediction = solver(project, model, coordinates)
    return summarize_stations(dataset, prediction)


def summarize_stations(dataset: ObservationDataset, prediction: DisplacementResult) -> BaselineResult:
    """Summarize supplied predictions, including arrays reopened from a run."""
    expected_xy = np.array([[r.x_m, r.y_m] for r in dataset.stations])
    if prediction.displacement_m.shape != (len(dataset.stations), 3) or prediction.xyz_m.shape != (len(dataset.stations), 3) or not np.all(np.isfinite(prediction.displacement_m)) or not np.array_equal(prediction.xyz_m[:, :2], expected_xy):
        raise ValidationError("Station predictions must match the supplied finite station coordinates and count.")
    observed = np.array([r.uz_observed_m for r in dataset.stations])
    line_metrics, role_metrics = {}, {}
    for line_id, role in dataset.metadata.line_roles.items():
        selected = np.array([r.line_id == line_id for r in dataset.stations])
        metrics = residual_metrics(observed[selected], prediction.uz_m[selected])
        reported = dataset.metadata.reported_rmse_m_by_line.get(line_id)
        line_metrics[line_id] = {"role": role, **metrics, "reported_rmse_m": reported, "rmse_minus_reported_m": metrics["rmse_m"] - reported if reported is not None else None}
    for role in ("fit", "test"):
        selected = np.array([dataset.metadata.line_roles[r.line_id] == role for r in dataset.stations])
        role_metrics[role] = residual_metrics(observed[selected], prediction.uz_m[selected])
    return BaselineResult(dataset, prediction, prediction.uz_m - observed, line_metrics, role_metrics)
