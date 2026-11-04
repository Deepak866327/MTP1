"""Bounded, deterministic calibration using fit-role stations exclusively."""

from dataclasses import dataclass, replace
import json
from pathlib import Path

import numpy as np
import scipy
from scipy.optimize import least_squares

from .config import FlatModel, InclinedModel, Model, Project, _keys, _unique_object, _reject_constant
from .evaluation import BaselineResult, evaluate_stations
from .geometry import ValidationError, finite_number
from .inclined import solve_inclined
from .observations import ObservationDataset
from .solver import solve_flat


@dataclass(frozen=True)
class CalibrationSettings:
    amplitude_bounds_m: tuple[float, float]
    influence_angle_bounds_deg: tuple[float, float]
    initial_guesses: tuple[tuple[float, float], ...]
    bounds_basis: str
    bounds_justification: str
    max_nfev: int = 200
    ftol: float = 1e-10
    xtol: float = 1e-10
    gtol: float = 1e-10

    def __post_init__(self):
        for name in ("amplitude_bounds_m", "influence_angle_bounds_deg"):
            bounds = getattr(self, name)
            if not isinstance(bounds, (tuple, list)) or len(bounds) != 2:
                raise ValidationError(f"{name} must contain lower and upper bounds.")
            lo, hi = [finite_number(v, name) for v in bounds]
            if not lo < hi or not np.isfinite(hi - lo):
                raise ValidationError(f"{name} requires finite lower < upper bounds.")
            object.__setattr__(self, name, (lo, hi))
        if self.amplitude_bounds_m[0] < 0:
            raise ValidationError("Amplitude bounds are nonnegative and measured in metres.")
        if not 0 < self.influence_angle_bounds_deg[0] < self.influence_angle_bounds_deg[1] < 90:
            raise ValidationError("Influence-angle bounds must be strictly inside (0, 90) degrees.")
        if self.bounds_basis not in ("synthetic_demonstration", "documented_site_information"):
            raise ValidationError("bounds_basis must identify synthetic_demonstration or documented_site_information.")
        if not isinstance(self.bounds_justification, str) or not self.bounds_justification.strip():
            raise ValidationError("Document the physical/site or synthetic basis for both parameter bounds.")
        lower, upper = np.array([self.amplitude_bounds_m, self.influence_angle_bounds_deg]).T
        if not isinstance(self.initial_guesses, (list, tuple)) or len(self.initial_guesses) < 2:
            raise ValidationError("Use at least two distinct initial guesses.")
        guesses = []
        for guess in self.initial_guesses:
            if not isinstance(guess, (tuple, list)) or len(guess) != 2:
                raise ValidationError("Each initial guess contains amplitude_m and influence_angle_deg.")
            values = tuple(finite_number(v, "initial guess") for v in guess)
            if not np.all((np.array(values) > lower) & (np.array(values) < upper)):
                raise ValidationError("Initial guesses must lie strictly inside the supplied bounds.")
            guesses.append(values)
        if len(set(guesses)) != len(guesses):
            raise ValidationError("Initial guesses must be distinct.")
        object.__setattr__(self, "initial_guesses", tuple(guesses))
        if isinstance(self.max_nfev, bool) or not isinstance(self.max_nfev, int) or self.max_nfev < 1:
            raise ValidationError("max_nfev must be a positive integer.")
        for name in ("ftol", "xtol", "gtol"):
            value = finite_number(getattr(self, name), name)
            if not np.finfo(float).eps < value < 1:
                raise ValidationError(f"{name} must be between machine epsilon and 1.")
            object.__setattr__(self, name, value)

    def to_dict(self):
        return {
            "schema_version": 1, "units": {"amplitude": "m", "angle": "degrees"},
            "amplitude_bounds_m": list(self.amplitude_bounds_m),
            "influence_angle_bounds_deg": list(self.influence_angle_bounds_deg),
            "initial_guesses": [{"amplitude_m": a, "influence_angle_deg": b} for a, b in self.initial_guesses],
            "bounds_basis": self.bounds_basis, "bounds_justification": self.bounds_justification,
            "max_nfev": self.max_nfev, "ftol": self.ftol, "xtol": self.xtol, "gtol": self.gtol,
        }

    @classmethod
    def from_dict(cls, data):
        _keys(data, ("schema_version", "units", "amplitude_bounds_m", "influence_angle_bounds_deg", "initial_guesses", "bounds_basis", "bounds_justification"), ("max_nfev", "ftol", "xtol", "gtol"), "calibration settings")
        if type(data["schema_version"]) is not int or data["schema_version"] != 1 or data["units"] != {"amplitude": "m", "angle": "degrees"}:
            raise ValidationError("Calibration settings require schema version 1 and explicit metre/degree units.")
        if not isinstance(data["initial_guesses"], list):
            raise ValidationError("initial_guesses must be an array.")
        guesses = []
        for guess in data["initial_guesses"]:
            _keys(guess, ("amplitude_m", "influence_angle_deg"), label="initial guess")
            guesses.append((guess["amplitude_m"], guess["influence_angle_deg"]))
        values = {k: v for k, v in data.items() if k not in ("schema_version", "units", "initial_guesses")}
        return cls(**values, initial_guesses=tuple(guesses))


def load_calibration_settings(path: str | Path) -> CalibrationSettings:
    with Path(path).open(encoding="utf-8-sig") as handle:
        return CalibrationSettings.from_dict(json.load(handle, object_pairs_hook=_unique_object, parse_constant=_reject_constant))


def parameter_vector(model: Model) -> np.ndarray:
    return np.array([model.smax_m if isinstance(model, FlatModel) else model.p_m, model.influence_angle_deg])


def model_with_parameters(model: Model, values) -> Model:
    amplitude = "smax_m" if isinstance(model, FlatModel) else "p_m"
    return replace(model, **{amplitude: float(values[0]), "influence_angle_deg": float(values[1])})


class CalibrationFailure(ValidationError):
    """No converged start: retain attempts without selecting a failed fit."""
    def __init__(self, attempts):
        super().__init__("No calibration start converged. Inspect attempts and fit-only settings; no fitted model selected.")
        self.attempts = attempts


@dataclass(frozen=True)
class CalibrationResult:
    project: Project
    manual_model: Model
    fitted_model: Model
    settings: CalibrationSettings
    fitted: BaselineResult
    manual: BaselineResult
    attempts: tuple[dict, ...]
    selected_start: int
    diagnostics: dict


def calibrate_stations(project: Project, model: Model, dataset: ObservationDataset, settings: CalibrationSettings) -> CalibrationResult:
    if not isinstance(model, (FlatModel, InclinedModel)) or not isinstance(settings, CalibrationSettings):
        raise ValidationError("Calibration requires a flat/inclined model and validated calibration settings.")
    if dataset.metadata.evidence != "synthetic_verification" and settings.bounds_basis == "synthetic_demonstration":
        raise ValidationError("Synthetic demonstration bounds cannot be used for field or surveyed-digitized observations.")
    # This is the only data passed to the objective. Test observations/coordinates,
    # source-reported metrics and uncertainties do not select or weight a fit.
    fit = tuple(s for s in dataset.stations if dataset.metadata.line_roles[s.line_id] == "fit")
    if len(fit) < 3:
        raise ValidationError("At least three fit-role stations are required for two-parameter calibration.")
    xyz = np.array([[s.x_m, s.y_m, project.surface_elevation_m] for s in fit])
    observed = np.array([s.uz_observed_m for s in fit])
    solver = solve_inclined if isinstance(model, InclinedModel) else solve_flat
    lower, upper = np.array([settings.amplitude_bounds_m, settings.influence_angle_bounds_deg]).T
    scale = upper - lower
    attempts, successful = [], []
    for index, guess in enumerate(settings.initial_guesses):
        trace = []

        def residual(parameters):
            values = solver(project, model_with_parameters(model, parameters), xyz).uz_m - observed
            sse = float(values @ values)
            if not np.all(np.isfinite(values)) or not np.isfinite(sse):
                raise ValidationError("Calibration residual/objective exceeds numerical range.")
            trace.append({"evaluation": len(trace) + 1, "amplitude_m": float(parameters[0]), "influence_angle_deg": float(parameters[1]), "sum_squared_residual_m2": sse})
            return values

        optimized = least_squares(residual, guess, bounds=(lower, upper), method="trf", jac="3-point", x_scale=scale, loss="linear", ftol=settings.ftol, xtol=settings.xtol, gtol=settings.gtol, max_nfev=settings.max_nfev)
        record = {
            "start_index": index, "initial_parameters": list(guess), "parameters": optimized.x.tolist(),
            "success": bool(optimized.success), "status": int(optimized.status), "message": optimized.message,
            "sum_squared_residual_m2": float(optimized.fun @ optimized.fun), "nfev": int(optimized.nfev),
            "njev": int(optimized.njev), "objective_evaluations_including_jacobian": len(trace),
            "optimality": float(optimized.optimality), "active_mask": optimized.active_mask.tolist(), "objective_trace": trace,
        }
        attempts.append(record)
        if optimized.success:
            successful.append((record["sum_squared_residual_m2"], index, optimized))
    if not successful:
        raise CalibrationFailure(tuple(attempts))
    _, selected, best = min(successful, key=lambda item: (item[0], item[1]))
    # Unit-aware diagnostics: derivatives are scaled by declared bound widths.
    jacobian = best.jac * scale
    singular = np.linalg.svd(jacobian, compute_uv=False)
    rank = int(np.linalg.matrix_rank(jacobian))
    condition = float(singular[0] / singular[-1]) if rank == 2 else None
    norms = np.linalg.norm(jacobian, axis=0)
    cosine = float(np.clip(jacobian[:, 0] @ jacobian[:, 1] / np.prod(norms), -1, 1)) if np.all(norms > 0) else None
    successful_parameters = np.array([a[2].x for a in successful])
    spread = np.ptp(successful_parameters, axis=0)
    # These are explicit diagnostic heuristics, not confidence levels.
    near_bounds = np.minimum(best.x - lower, upper - best.x) / scale <= 1e-6
    warnings = []
    if rank < 2 or condition is None or condition > 1e4 or (cosine is not None and abs(cosine) > 0.995):
        warnings.append("Weak local parameter identifiability: inspect fit coverage; no uncertainty interval is established.")
    if np.any(near_bounds):
        warnings.append("At least one fitted parameter is near a declared bound; the solution is constrained by that choice.")
    if np.any(spread / scale > 1e-4):
        warnings.append("Successful starts disagree by more than 1e-4 of a bound width; inspect all minima.")
    if len(successful) != len(attempts):
        warnings.append("Some starts did not converge; their attempts are retained and excluded from selection.")
    diagnostics = {
        "parameter_order": ["smax_m" if isinstance(model, FlatModel) else "p_m", "influence_angle_deg"],
        "fit_station_ids": [s.station_id for s in fit], "fit_line_ids": [k for k, v in dataset.metadata.line_roles.items() if v == "fit"],
        "objective": "Unweighted sum of squared (predicted global Uz - observed canonical Uz), m^2; optimizer cost = SSE / 2.",
        "optimizer": "scipy.optimize.least_squares", "scipy_version": scipy.__version__, "numpy_version": np.__version__,
        "method": "trf", "jacobian": "3-point finite difference", "loss": "linear", "x_scale": scale.tolist(),
        "selection": "Smallest fit-only SSE among converged starts; ties use earliest supplied start.",
        "scaled_jacobian_singular_values_m": singular.tolist(), "scaled_jacobian_rank": rank,
        "fit_jacobian": best.jac.tolist(), "fit_jacobian_column_units": ["m/m", "m/degree"],
        "scaled_jacobian_condition_number": condition, "sensitivity_column_cosine": cosine,
        "successful_start_count": len(successful), "successful_parameter_spread": spread.tolist(),
        "near_bounds": near_bounds.tolist(), "warnings": warnings,
        "identifiability_thresholds": {"condition_number": 1e4, "absolute_column_cosine": 0.995, "relative_bound_distance": 1e-6, "relative_start_spread": 1e-4},
        "confidence_intervals_established": False, "testing_used_for_selection": False,
    }
    fitted_model = model_with_parameters(model, best.x)
    # Selection is now complete. Frozen models see held-out observations once.
    fitted = evaluate_stations(project, fitted_model, dataset)
    manual = evaluate_stations(project, model, dataset)
    return CalibrationResult(project, model, fitted_model, settings, fitted, manual, tuple(attempts), selected, diagnostics)
