"""Provenance, direct station evaluation and honest digitized comparison checks."""

from contextlib import redirect_stderr, redirect_stdout
import csv
from dataclasses import replace
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from subsidence import FlatModel, InclinedModel, ValidationError, evaluate_stations, load_model, load_observations, load_project, residual_metrics, solve_flat, solve_inclined
from subsidence.cli import main
from subsidence.config import Spacing
from subsidence.digitization import _tick_distance, load_digitized_report
from subsidence.observations import ObservationMetadata
from subsidence.phase5_results import export_baseline, export_digitized_report
from subsidence.phase5_verification import synthetic_metadata


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/adriyala_digitized/report_traces.json"
CSV_TEXT = "station_id,line_id,x_m,y_m,uz_observed_m,distance_m\nF1,FIT_SYNTHETIC,-31.5,7.25,1,0\nF2,FIT_SYNTHETIC,17.75,-3.5,2,50\nT1,TEST_SYNTHETIC,-7.2,41.3,3,0\nT2,TEST_SYNTHETIC,59.8,13.7,4,75\n"


def write_inputs(root, csv_text=CSV_TEXT, metadata=None):
    csv_path, metadata_path = Path(root) / "observations.csv", Path(root) / "metadata.json"
    csv_path.write_text(csv_text, encoding="utf-8")
    metadata_path.write_text(json.dumps(metadata or synthetic_metadata()), encoding="utf-8")
    return csv_path, metadata_path


def project():
    return load_project(ROOT / "examples/synthetic_flat.json")


class ObservationInputTests(unittest.TestCase):
    def test_metadata_and_positive_settlement_conversion_preserve_raw_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path, metadata_path = write_inputs(tmp)
            data = load_observations(csv_path, metadata_path)
            self.assertEqual(data.raw_csv, csv_path.read_bytes())
            self.assertEqual(data.raw_metadata, metadata_path.read_bytes())
            assert_array_equal([s.uz_input_m for s in data.stations], [1, 2, 3, 4])
            assert_array_equal([s.uz_observed_m for s in data.stations], [-1, -2, -3, -4])
            self.assertEqual(data.metadata.line_roles["TEST_SYNTHETIC"], "test")

    def test_up_positive_sign_and_no_distance_columns_are_supported(self):
        text = "station_id,line_id,x_m,y_m,uz_observed_m\nA,FIT_SYNTHETIC,0,0,-1\nB,TEST_SYNTHETIC,1,1,-2\n"
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_inputs(tmp, text, synthetic_metadata() | {"vertical_sign": "up_positive"})
            data = load_observations(*paths)
            assert_array_equal([s.uz_observed_m for s in data.stations], [-1, -2])
            self.assertTrue(all(s.distance_m is None for s in data.stations))

    def test_utf8_bom_is_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_inputs(tmp)
            paths[0].write_text(CSV_TEXT, encoding="utf-8-sig")
            self.assertEqual(len(load_observations(*paths).stations), 4)

    def test_metadata_rejects_unknown_units_missing_datum_stage_and_roles(self):
        variants = [{"schema_version": True}, {"units": {"length": "ft"}}, {"vertical_datum": None}, {"coordinate_reference": ""}, {"measurement_stage": ""}, {"provenance": None}, {"evidence": "validated"}, {"vertical_sign": "unknown"}, {"line_roles": {"a": "fit"}}, {"line_roles": {"a": "fit", "b": "holdout"}}, {"extra": 1}]
        for variant in variants:
            with self.subTest(variant=variant), self.assertRaises(ValidationError):
                ObservationMetadata.from_dict(synthetic_metadata() | variant)

    def test_reported_metrics_require_source_and_known_line_ids(self):
        for values in ({"reported_rmse_m_by_line": {"other": 0.25}, "reported_metrics_source": "source"}, {"reported_rmse_m_by_line": {"FIT_SYNTHETIC": 0.25}}, {"reported_rmse_m_by_line": {"FIT_SYNTHETIC": -1}, "reported_metrics_source": "source"}):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                ObservationMetadata.from_dict(synthetic_metadata() | values)

    def test_station_ids_unknown_lines_and_malformed_values_are_rejected(self):
        changes = [CSV_TEXT.replace("T1,", "F1,"), CSV_TEXT.replace("TEST_SYNTHETIC", "UNKNOWN"), CSV_TEXT.replace("-31.5", "nan"), CSV_TEXT.replace("7.25", "True"), CSV_TEXT.replace("F1,FIT", ",FIT"), CSV_TEXT.replace("F1,FIT_SYNTHETIC,-31.5,7.25,1,0", "F1,FIT_SYNTHETIC,-31.5,7.25,1,0,extra")]
        with tempfile.TemporaryDirectory() as tmp:
            for text in changes:
                paths = write_inputs(tmp, text)
                with self.subTest(text=text), self.assertRaises(ValidationError):
                    load_observations(*paths)

    def test_csv_columns_empty_data_and_missing_line_rejected(self):
        variants = ["station_id,line_id,x_m,y_m,uz_observed_m\n", CSV_TEXT.replace("x_m", "longitude"), CSV_TEXT.replace("distance_m", "x_m"), "\n".join(CSV_TEXT.splitlines()[:3]) + "\n"]
        with tempfile.TemporaryDirectory() as tmp:
            for text in variants:
                with self.subTest(text=text), self.assertRaises(ValidationError):
                    load_observations(*write_inputs(tmp, text))

    def test_mixed_duplicate_or_negative_line_distances_are_rejected(self):
        variants = [CSV_TEXT.replace(",2,50", ",2,"), CSV_TEXT.replace(",2,50", ",2,0"), CSV_TEXT.replace(",2,50", ",2,-50")]
        with tempfile.TemporaryDirectory() as tmp:
            for text in variants:
                with self.subTest(text=text), self.assertRaises(ValidationError):
                    load_observations(*write_inputs(tmp, text))

    def test_empty_adriyala_templates_do_not_fabricate_observations(self):
        with self.assertRaises(ValidationError):
            load_observations(ROOT / "examples/adriyala_observations.template.csv", ROOT / "examples/adriyala_observations.template.json")


class MetricAndPredictionTests(unittest.TestCase):
    def test_rmse_mae_bias_have_independently_known_values(self):
        result = residual_metrics([-1, -2], [0, 0])
        self.assertEqual(result["count"], 2)
        self.assertAlmostEqual(result["rmse_m"], math.sqrt(2.5))
        self.assertAlmostEqual(result["mae_m"], 1.5)
        self.assertAlmostEqual(result["bias_m"], 1.5)
        self.assertEqual(residual_metrics([0, 1], [0, 1])["rmse_m"], 0)

    def test_invalid_metric_arrays_are_rejected(self):
        for observed, predicted in (([], []), ([1], [1, 2]), ([float("nan")], [0]), ([[1]], [[0]]), ([1e308], [-1e308])):
            with self.subTest(observed=observed), self.assertRaises(ValidationError):
                residual_metrics(observed, predicted)

    def test_fixed_model_all_groups_and_exact_off_grid_coordinates(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = load_observations(*write_inputs(tmp))
            p, model = project(), FlatModel(1, 20)
            with patch("subsidence.evaluation.solve_flat", wraps=solve_flat) as solver:
                result = evaluate_stations(p, model, data)
            self.assertEqual(solver.call_count, 1)
            self.assertEqual(solver.call_args.args[1], model)
            expected = np.array([[s.x_m, s.y_m, 0] for s in data.stations])
            assert_array_equal(result.prediction.xyz_m, expected)
            self.assertEqual(result.role_metrics["fit"]["count"], 2)
            self.assertEqual(result.role_metrics["test"]["count"], 2)
            changed_grid = replace(p, surface_grid=Spacing(17, 31))
            assert_array_equal(evaluate_stations(changed_grid, model, data).prediction.displacement_m, result.prediction.displacement_m)

    def test_inclined_dispatch_and_reported_metric_differences(self):
        metadata = synthetic_metadata() | {"reported_rmse_m_by_line": {"FIT_SYNTHETIC": 0.25, "TEST_SYNTHETIC": 0.26}, "reported_metrics_source": "Synthetic test reference only"}
        with tempfile.TemporaryDirectory() as tmp:
            data = load_observations(*write_inputs(tmp, metadata=metadata))
            p = load_project(ROOT / "examples/synthetic_inclined.json")
            with patch("subsidence.evaluation.solve_inclined", wraps=solve_inclined) as solver:
                result = evaluate_stations(p, InclinedModel(1.3, 20), data)
            self.assertEqual(solver.call_count, 1)
            metric = result.line_metrics["TEST_SYNTHETIC"]
            self.assertAlmostEqual(metric["rmse_minus_reported_m"], metric["rmse_m"] - 0.26)


class DigitizedReportTests(unittest.TestCase):
    def test_trace_audit_has_no_global_coordinates_or_fresh_model_predictions(self):
        with patch("subsidence.inclined.solve_inclined", side_effect=AssertionError("Digitized audit must not evaluate rebuilt solver")):
            report = load_digitized_report(MANIFEST)
        self.assertEqual([l.role for l in report.lines], ["fit", "test"])
        self.assertEqual([len(l.pixel_samples) for l in report.lines], [17, 27])
        self.assertEqual([len(l.comparison_distance_m) for l in report.lines], [45, 40])
        for line in report.lines:
            self.assertTrue(np.isfinite(line.observed_uz_m).all())
            self.assertFalse(hasattr(line, "station_id"))
            self.assertFalse(hasattr(line, "x_m"))
            self.assertEqual(line.metrics["count"], len(line.comparison_distance_m))
            independently = np.sqrt(np.mean((line.compared_reported_uz_m - line.compared_observed_uz_m)**2))
            self.assertAlmostEqual(line.metrics["rmse_m"], independently)

    def test_tick_interpolation_and_limited_endpoint_extension(self):
        ticks = np.array([[10, 0], [20, 100], [40, 200]], dtype=float)
        assert_allclose(_tick_distance(np.array([5, 10, 15, 20, 30, 40, 50]), ticks), [-50, 0, 50, 100, 150, 200, 250])
        with self.assertRaises(ValidationError):
            _tick_distance(np.array([100.0]), ticks)

    def test_digitization_source_hashes_and_evidence_are_checked(self):
        original = json.loads(MANIFEST.read_text())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.json"
            for changes in ({"source_pdf_sha256": "wrong"}, {"evidence": "field_measurements"}, {"comparison_spacing_m": 0}, {"vertical_uncertainty_m_assumed": -1}):
                data = original | {"source_root_relative": str(ROOT)} | changes
                path.write_text(json.dumps(data), encoding="utf-8")
                with self.subTest(changes=changes), self.assertRaises(ValidationError):
                    load_digitized_report(path)

    def test_corrupt_border_curve_and_duplicate_line_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.json"
            for corruption in ("border", "curve", "duplicate"):
                data = json.loads(MANIFEST.read_text())
                data["source_root_relative"] = str(ROOT)
                if corruption == "border":
                    data["lines"][0]["bottom_border_px"] = data["lines"][0]["top_border_px"]
                elif corruption == "curve":
                    data["lines"][0]["samples_px_observed_y_predicted_y"][0][1] = 0
                else:
                    data["lines"][1]["line_id"] = data["lines"][0]["line_id"]
                path.write_text(json.dumps(data), encoding="utf-8")
                with self.subTest(corruption=corruption), self.assertRaises(ValidationError):
                    load_digitized_report(path)


class BaselineExportAndCliTests(unittest.TestCase):
    def test_station_bundle_preserves_raw_bytes_and_recomputes(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = load_observations(*write_inputs(tmp))
            p, model = project(), FlatModel(0, 20)
            result = evaluate_stations(p, model, data)
            output = Path(tmp) / "result"
            summary = export_baseline(p, model, result, output)
            self.assertEqual(summary["status"], "synthetic_station_pipeline_verification")
            self.assertFalse(summary["exact_original_reproduction_established"])
            self.assertFalse(summary["parameters_fitted_in_this_run"])
            self.assertEqual((output / "raw_observations.csv").read_bytes(), data.raw_csv)
            self.assertEqual((output / "raw_metadata.json").read_bytes(), data.raw_metadata)
            reloaded = load_observations(output / "raw_observations.csv", output / "observation_metadata.json")
            rebuilt = evaluate_stations(load_project(output / "project.json"), load_model(output / "model.json"), reloaded)
            with np.load(output / "station_predictions.npz", allow_pickle=False) as arrays:
                assert_array_equal(arrays["displacement_m"], rebuilt.prediction.displacement_m)
                assert_array_equal(arrays["residual_m"], [1, 2, 3, 4])
            ET.parse(output / "line_001.svg")
            with self.assertRaisesRegex(ValidationError, "empty"):
                export_baseline(p, model, result, output)

    def test_export_without_distances_uses_station_ids_not_invented_distance(self):
        text = "station_id,line_id,x_m,y_m,uz_observed_m\nA,FIT_SYNTHETIC,0,0,1\nB,TEST_SYNTHETIC,1,1,2\n"
        with tempfile.TemporaryDirectory() as tmp:
            data = load_observations(*write_inputs(tmp, text))
            p, model = project(), FlatModel(0, 20)
            summary = export_baseline(p, model, evaluate_stations(p, model, data), Path(tmp) / "result")
            self.assertTrue(all(f["abscissa"] == "station_id_input_order" for f in summary["figures"]))

    def test_mismatched_settings_and_project_do_not_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = load_observations(*write_inputs(tmp))
            p, model = project(), FlatModel(0, 20)
            result = evaluate_stations(p, model, data)
            with self.assertRaises(ValidationError):
                export_baseline(p, FlatModel(1, 20), result, Path(tmp) / "bad")
            self.assertFalse((Path(tmp) / "bad").exists())

    def test_digitized_bundle_is_replayable_and_not_a_station_comparison(self):
        report = load_digitized_report(MANIFEST)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "audit"
            summary = export_digitized_report(report, output)
            self.assertFalse(summary["rebuilt_engine_station_comparison_completed"])
            self.assertFalse(summary["exact_original_reproduction_established"])
            saved = load_digitized_report(output / "digitization.json")
            assert_allclose([l.metrics["rmse_m"] for l in saved.lines], [l.metrics["rmse_m"] for l in report.lines], rtol=0, atol=0)
            with (output / "digitized_comparison.csv").open() as handle:
                reader = csv.DictReader(handle)
                self.assertNotIn("station_id", reader.fieldnames)
                self.assertNotIn("x_m", reader.fieldnames)
                self.assertEqual(len(list(reader)), 85)
            ET.parse(output / "published_line_002_pixel_audit.svg")
            self.assertIn("incomplete", (output / "baseline_report.md").read_text())

    def test_cli_station_comparison_and_incomplete_template(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            csv_path, metadata = write_inputs(tmp)
            arguments = ["evaluate-stations", str(ROOT / "examples/synthetic_flat.json"), "--model", str(ROOT / "examples/flat_model.json"), "--observations", str(csv_path), "--metadata", str(metadata), "--output", str(Path(tmp) / "baseline")]
            self.assertEqual(main(arguments), 0)
            with redirect_stderr(io.StringIO()) as error:
                self.assertEqual(main(["evaluate-stations", str(ROOT / "examples/adriyala_geometry.json"), "--model", str(ROOT / "examples/adriyala_inclined_model.json"), "--observations", str(ROOT / "examples/adriyala_observations.template.csv"), "--metadata", str(ROOT / "examples/adriyala_observations.template.json"), "--output", str(Path(tmp) / "unavailable")]), 2)
            self.assertIn("must be documented", error.getvalue())
            self.assertFalse((Path(tmp) / "unavailable").exists())

    def test_cli_audit_and_synthetic_verification(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            self.assertEqual(main(["audit-report-profiles", str(MANIFEST), "--output", str(Path(tmp) / "audit")]), 0)
            output = Path(tmp) / "verification"
            self.assertEqual(main(["verify-baseline", "--output", str(output)]), 0)
            report = json.loads((output / "verification.json").read_text())
            self.assertTrue(report["passed"])
            self.assertEqual(len(report["checks"]), 9)
            self.assertFalse(report["field_validation_established"])


if __name__ == "__main__":
    unittest.main()
