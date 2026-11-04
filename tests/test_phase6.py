"""Inverse recovery, fit/test isolation, failure diagnostics and replay."""

from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal
from scipy.optimize import least_squares

from subsidence import CalibrationFailure, CalibrationSettings, FlatModel, ValidationError, calibrate_stations, evaluate_stations, load_calibration_settings, load_model, load_observations, load_project
from subsidence.calibration import parameter_vector
from subsidence.cli import main
from subsidence.phase6_results import export_calibration, export_calibration_failure
from subsidence.phase6_verification import AMPLITUDE_ATOL_M, ANGLE_ATOL_DEG, HELD_OUT_RMSE_ATOL_M, synthetic_settings, write_synthetic_inputs
from subsidence.solver import solve_flat


class CalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.project, cls.truth, cls.manual, cls.data = write_synthetic_inputs(cls.root / "flat_inputs", independent=False)
        cls.settings = synthetic_settings()
        cls.result = calibrate_stations(cls.project, cls.manual, cls.data, cls.settings)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_discrete_known_parameters_recovered_from_all_starts(self):
        for attempt in self.result.attempts:
            self.assertTrue(attempt["success"])
            assert_allclose(attempt["parameters"], [1.2, 23], atol=1e-7, rtol=0)
        self.assertLess(self.result.fitted.role_metrics["test"]["rmse_m"], 1e-10)

    def test_flat_and_inclined_recovery_against_independent_integrals(self):
        for inclined in (False, True):
            with self.subTest(inclined=inclined), tempfile.TemporaryDirectory() as tmp:
                p, truth, manual, data = write_synthetic_inputs(Path(tmp) / "inputs", inclined=inclined)
                result = calibrate_stations(p, manual, data, self.settings)
                errors = np.abs(parameter_vector(result.fitted_model) - parameter_vector(truth))
                self.assertLess(errors[0], AMPLITUDE_ATOL_M)
                self.assertLess(errors[1], ANGLE_ATOL_DEG)
                self.assertLess(result.fitted.role_metrics["test"]["rmse_m"], HELD_OUT_RMSE_ATOL_M)
                self.assertEqual(result.diagnostics["scaled_jacobian_rank"], 2)
                self.assertFalse(result.diagnostics["warnings"])
                if inclined:
                    original = manual.to_dict()
                    fitted = result.fitted_model.to_dict()
                    for key in set(original) - {"p_m", "influence_angle_deg"}:
                        self.assertEqual(original[key], fitted[key])

    def test_test_values_coordinates_and_reported_errors_cannot_select_fit(self):
        stations = tuple(replace(s, uz_observed_m=s.uz_observed_m + 8, x_m=s.x_m + 17, y_m=s.y_m - 9) if self.data.metadata.line_roles[s.line_id] == "test" else s for s in self.data.stations)
        metadata = replace(self.data.metadata, reported_rmse_m_by_line={"FIT_SYNTHETIC": 999, "TEST_SYNTHETIC": 0}, reported_metrics_source="Deliberately irrelevant test fixture")
        altered = calibrate_stations(self.project, self.manual, replace(self.data, stations=stations, metadata=metadata), self.settings)
        self.assertEqual(altered.fitted_model, self.result.fitted_model)
        self.assertEqual(altered.attempts, self.result.attempts)
        self.assertEqual(altered.diagnostics, self.result.diagnostics)
        self.assertGreater(altered.fitted.role_metrics["test"]["rmse_m"], 7)

    def test_objective_receives_only_fit_coordinates(self):
        fit_xyz = [[s.x_m, s.y_m, 0] for s in self.data.stations if self.data.metadata.line_roles[s.line_id] == "fit"]
        with patch("subsidence.calibration.solve_flat", wraps=solve_flat) as solver:
            calibrate_stations(self.project, self.manual, self.data, self.settings)
        for call in solver.call_args_list:
            assert_array_equal(call.args[2], fit_xyz)

    def test_test_evaluation_uses_frozen_fitted_and_manual_models(self):
        with patch("subsidence.calibration.evaluate_stations", wraps=evaluate_stations) as evaluator:
            result = calibrate_stations(self.project, self.manual, self.data, self.settings)
        self.assertEqual(evaluator.call_count, 2)
        self.assertEqual(evaluator.call_args_list[0].args[1], result.fitted_model)
        self.assertEqual(evaluator.call_args_list[1].args[1], self.manual)
        self.assertEqual(result.fitted.prediction.metadata["settings"], result.fitted_model.to_dict())

    def test_repeatability_includes_objective_trace(self):
        repeated = calibrate_stations(self.project, self.manual, self.data, self.settings)
        self.assertEqual(self.result.attempts, repeated.attempts)
        self.assertEqual(self.result.fitted_model, repeated.fitted_model)

    def test_uncertainty_values_do_not_introduce_unrequested_weights(self):
        stations = tuple(replace(s, uncertainty_m=(i + 1) * 0.5) for i, s in enumerate(self.data.stations))
        result = calibrate_stations(self.project, self.manual, replace(self.data, stations=stations), self.settings)
        self.assertEqual(self.result.attempts, result.attempts)

    def test_noisy_fit_uses_unweighted_sse_and_saves_residual_vector(self):
        stations = tuple(replace(s, uz_observed_m=s.uz_observed_m + 0.01 * np.sin(i)) if self.data.metadata.line_roles[s.line_id] == "fit" else s for i, s in enumerate(self.data.stations))
        result = calibrate_stations(self.project, self.manual, replace(self.data, stations=stations), self.settings)
        error = result.fitted.residual_m[:31]
        self.assertAlmostEqual(float(error @ error), result.attempts[result.selected_start]["sum_squared_residual_m2"], places=14)
        self.assertGreater(result.fitted.role_metrics["fit"]["rmse_m"], 0)
        self.assertLess(result.fitted.role_metrics["fit"]["rmse_m"], result.manual.role_metrics["fit"]["rmse_m"])

    def test_rank_deficient_fit_warns_without_claiming_identifiability(self):
        first = self.data.stations[15]
        stations = tuple(replace(s, x_m=first.x_m, y_m=first.y_m, uz_observed_m=first.uz_observed_m) if self.data.metadata.line_roles[s.line_id] == "fit" else s for s in self.data.stations)
        result = calibrate_stations(self.project, self.manual, replace(self.data, stations=stations), self.settings)
        self.assertLess(result.diagnostics["scaled_jacobian_rank"], 2)
        self.assertIsNone(result.diagnostics["scaled_jacobian_condition_number"])
        self.assertTrue(any("identifiability" in w for w in result.diagnostics["warnings"]))
        self.assertFalse(result.diagnostics["confidence_intervals_established"])

    def test_bound_constrained_solution_is_flagged(self):
        settings = replace(self.settings, amplitude_bounds_m=(0, 0.9), initial_guesses=((0.3, 15), (0.7, 28)))
        result = calibrate_stations(self.project, self.manual, self.data, settings)
        self.assertLessEqual(result.fitted_model.smax_m, 0.9)
        self.assertTrue(result.diagnostics["near_bounds"][0])
        self.assertTrue(any("bound" in w for w in result.diagnostics["warnings"]))

    def test_all_failed_starts_do_not_select_or_evaluate_test_data(self):
        settings = replace(self.settings, max_nfev=1)
        with patch("subsidence.calibration.evaluate_stations") as evaluation:
            with self.assertRaises(CalibrationFailure) as caught:
                calibrate_stations(self.project, self.manual, self.data, settings)
        evaluation.assert_not_called()
        self.assertTrue(all(not a["success"] for a in caught.exception.attempts))
        with tempfile.TemporaryDirectory() as tmp:
            summary = export_calibration_failure(self.project, self.manual, self.data, settings, caught.exception, tmp)
            self.assertFalse(summary["fitted_model_selected"])
            self.assertFalse((Path(tmp) / "fitted_model.json").exists())
            self.assertTrue((Path(tmp) / "objective_trace.csv").exists())

    def test_partial_failure_is_reported_and_excluded(self):
        def limited(fun, guess, **kwargs):
            if guess == self.settings.initial_guesses[0]:
                kwargs["max_nfev"] = 1
            return least_squares(fun, guess, **kwargs)
        with patch("subsidence.calibration.least_squares", side_effect=limited):
            result = calibrate_stations(self.project, self.manual, self.data, self.settings)
        self.assertFalse(result.attempts[0]["success"])
        self.assertNotEqual(result.selected_start, 0)
        self.assertEqual(result.diagnostics["successful_start_count"], 2)
        self.assertTrue(any("did not converge" in w for w in result.diagnostics["warnings"]))

    def test_at_least_three_fit_stations_are_required(self):
        stations = self.data.stations[:2] + self.data.stations[31:]
        with self.assertRaises(ValidationError):
            calibrate_stations(self.project, self.manual, replace(self.data, stations=stations), self.settings)

    def test_synthetic_bounds_cannot_be_used_for_field_data(self):
        data = replace(self.data, metadata=replace(self.data.metadata, evidence="field_measurements"))
        with self.assertRaises(ValidationError):
            calibrate_stations(self.project, self.manual, data, self.settings)
        # Site bounds are caller-documented; no automatic physical truth claim.
        settings = replace(self.settings, bounds_basis="documented_site_information", bounds_justification="Fixture declaration for input-routing test only.")
        result = calibrate_stations(self.project, self.manual, data, settings)
        self.assertEqual(result.fitted_model, self.result.fitted_model)

    def test_settings_round_trip_and_strict_schema(self):
        self.assertEqual(CalibrationSettings.from_dict(self.settings.to_dict()), self.settings)
        self.assertEqual(load_calibration_settings(self.root / "flat_inputs/calibration_settings.json"), self.settings)
        variants = [{"schema_version": True}, {"units": {"amplitude": "dimensionless", "angle": "degrees"}}, {"extra": 1}, {"initial_guesses": "bad"}, {"initial_guesses": [{"amplitude_m": 1}]}]
        for variant in variants:
            with self.subTest(variant=variant), self.assertRaises(ValidationError):
                CalibrationSettings.from_dict(self.settings.to_dict() | variant)

    def test_invalid_bounds_starts_controls_and_justification_are_rejected(self):
        variants = [{"amplitude_bounds_m": (-1, 2)}, {"amplitude_bounds_m": (1, 1)}, {"amplitude_bounds_m": (0, float("inf"))}, {"amplitude_bounds_m": (False, 2)}, {"influence_angle_bounds_deg": (0, 40)}, {"influence_angle_bounds_deg": (10, 90)}, {"initial_guesses": ((1, 20),)}, {"initial_guesses": ((1, 20), (1, 20))}, {"initial_guesses": ((0, 20), (1, 20))}, {"max_nfev": True}, {"max_nfev": 0}, {"ftol": 0}, {"xtol": float("nan")}, {"gtol": 1}, {"bounds_basis": "default"}, {"bounds_justification": ""}]
        for variant in variants:
            with self.subTest(variant=variant), self.assertRaises(ValidationError):
                replace(self.settings, **variant)

    def test_duplicate_and_nonfinite_json_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            for text in ('{"schema_version":1,"schema_version":1}', '{"amplitude_bounds_m":[0, NaN]}'):
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_calibration_settings(path)

    def test_export_replays_inputs_model_predictions_and_finite_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "run"
            summary = export_calibration(self.result, target)
            saved = load_model(target / "fitted_model.json")
            data = load_observations(target / "fitted_evaluation/raw_observations.csv", target / "fitted_evaluation/raw_metadata.json")
            replayed = evaluate_stations(load_project(target / "project.json"), saved, data)
            assert_array_equal(replayed.prediction.displacement_m, self.result.fitted.prediction.displacement_m)
            self.assertEqual(data.raw_csv, self.data.raw_csv)
            self.assertEqual(data.raw_metadata, self.data.raw_metadata)
            json.dumps(summary, allow_nan=False)
            self.assertFalse(summary["exact_original_reproduction_established"])
            self.assertEqual(summary["evidence"], "synthetic_verification")
            self.assertFalse(summary["diagnostics"]["testing_used_for_selection"])
            self.assertEqual(len(summary["fit_residual_vector_m"]), 31)
            self.assertTrue((target / "fitted_evaluation/line_002.png").is_file())
            with self.assertRaises(ValidationError):
                export_calibration(self.result, target)

    def test_cli_calibration_and_failure_exit_codes(self):
        inputs = self.root / "flat_inputs"
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["calibrate-stations", str(inputs / "project.json"), "--model", str(inputs / "manual_model.json"), "--observations", str(inputs / "observations.csv"), "--metadata", str(inputs / "metadata.json"), "--settings", str(inputs / "calibration_settings.json"), "--output", str(Path(tmp) / "success")]
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(argv), 0)
            settings = Path(tmp) / "failed_settings.json"
            settings.write_text(json.dumps(replace(self.settings, max_nfev=1).to_dict()), encoding="utf-8")
            argv[-3] = str(settings)
            argv[-1] = str(Path(tmp) / "failed")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(argv), 1)
            failed = json.loads((Path(tmp) / "failed/calibration_summary.json").read_text())
            self.assertFalse(failed["testing_evaluated"])
            argv[-3] = str(inputs / "calibration_settings.json")
            argv[argv.index("--observations") + 1] = str(Path(__file__).resolve().parents[1] / "examples/adriyala_observations.template.csv")
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(argv), 2)


if __name__ == "__main__":
    unittest.main()
