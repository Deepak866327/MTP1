"""Desktop workflow parity, cache behavior, archive integrity and UI actions."""

from contextlib import redirect_stdout
from dataclasses import replace
import gc
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import warnings
import zipfile

import numpy as np
from numpy.testing import assert_array_equal

from subsidence import FlatModel, ProfileLine, ValidationError, solve_flat, solve_inclined
from subsidence.cli import main
from subsidence.desktop_plots import field_figure
from subsidence.phase6_verification import synthetic_settings, write_synthetic_inputs
from subsidence.workspace import ProjectDocument, calibrate_document, compute_document, export_run, load_document, open_run, save_document


def rewrite_archive(source, destination, changes, *, refresh_hashes=False):
    with zipfile.ZipFile(source) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    files.update(changes)
    if refresh_hashes:
        manifest = json.loads(files["manifest.json"])
        manifest["files_sha256"] = {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items() if name != "manifest.json"}
        files["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, raw in files.items():
            archive.writestr(name, raw)


class WorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from subsidence.workspace import example_document
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.flat_doc = example_document("Synthetic flat")
        cls.flat = compute_document(cls.flat_doc)
        cls.flat_zip = cls.root / "flat.zip"
        export_run(cls.flat, cls.flat_zip)
        p, _, model, data = write_synthetic_inputs(cls.root / "inputs", inclined=True)
        cls.fit_doc = ProjectDocument(p, model, observations=data, calibration_settings=synthetic_settings())
        cls.fitted = calibrate_document(cls.fit_doc)
        cls.fit_zip = cls.root / "calibration.zip"
        export_run(cls.fitted, cls.fit_zip)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_desktop_computation_matches_core_flat_and_inclined(self):
        from subsidence.workspace import example_document
        for name, solver in (("Synthetic flat", solve_flat), ("Synthetic inclined", solve_inclined)):
            doc = example_document(name)
            run = compute_document(doc)
            expected = solver(doc.project, doc.model, run.surface.xyz_m)
            assert_array_equal(run.displacement.displacement_m, expected.displacement_m)

    def test_display_profile_and_statistics_reuse_cached_arrays(self):
        with patch("subsidence.workspace.solve_flat", side_effect=AssertionError("Unexpected solve")), patch("subsidence.workspace.solve_inclined", side_effect=AssertionError("Unexpected solve")):
            for name in ("Ux", "Uy", "Uz", "Ex", "Ey", "Settlement"):
                self.assertEqual(self.flat.values(name).shape, (40, 50))
                self.assertTrue(np.isfinite(self.flat.statistics(name)["mean"]))
                figure = field_figure(self.flat, name, "plasma")
                self.assertEqual(len(figure.axes), 2)
            profile = self.flat.profile(ProfileLine("Oblique", (-300, -200), (300, 200), 31))
            self.assertEqual(len(profile.distance_m), 31)

    def test_strain_map_has_symmetric_signed_scale_centered_at_zero(self):
        figure = field_figure(self.flat, "Ex", "viridis")
        artist = figure.axes[0].collections[0]
        self.assertEqual(artist.norm.vcenter, 0)
        self.assertEqual(artist.norm.vmin, -artist.norm.vmax)
        self.assertEqual(artist.cmap.name, "RdBu_r")

    def test_hover_uses_actual_cell_centers_units_and_boundary_flags(self):
        point = self.flat.inspect(-500, -400, "Ex")
        self.assertEqual((point["x_m"], point["y_m"]), (-490, -390))
        self.assertTrue(point["one_sided_boundary"])
        self.assertEqual(point["unit"], "mm/m")
        self.assertEqual(self.flat.inspect(500, 400, "Uz")["value"], self.flat.displacement.uz_m[-1, -1])
        self.assertIsNone(self.flat.inspect(501, 0, "Uz"))
        self.assertIsNone(self.flat.inspect(float("nan"), 0, "Uz"))

    def test_desktop_document_round_trip_retains_input_bytes_and_provenance(self):
        path = self.root / "project.json"
        save_document(self.fit_doc, path)
        document = load_document(path)
        self.assertEqual(document.to_dict(), self.fit_doc.to_dict())
        self.assertEqual(document.observations.raw_csv, self.fit_doc.observations.raw_csv)
        self.assertEqual(document.observations.raw_metadata, self.fit_doc.observations.raw_metadata)

    def test_archive_reopens_without_solver_and_preserves_arrays_settings_and_evidence(self):
        with patch("subsidence.workspace.solve_flat", side_effect=AssertionError("Unexpected solve")), patch("subsidence.workspace.solve_inclined", side_effect=AssertionError("Unexpected solve")), patch("subsidence.workspace.evaluate_stations", side_effect=AssertionError("Unexpected station solve")):
            run = open_run(self.fit_zip)
        assert_array_equal(run.displacement.displacement_m, self.fitted.displacement.displacement_m)
        assert_array_equal(run.strain.ex, self.fitted.strain.ex)
        assert_array_equal(run.evaluation.residual_m, self.fitted.evaluation.residual_m)
        self.assertEqual(run.evaluation.role_metrics, self.fitted.evaluation.role_metrics)
        self.assertEqual(run.document.to_dict(), self.fitted.document.to_dict())
        self.assertEqual(run.calibration_summary["evidence"], "synthetic_verification")
        self.assertFalse(run.calibration_summary["diagnostics"]["testing_used_for_selection"])
        self.assertEqual(run.evaluation.prediction.metadata["evaluation_point_count"], len(run.document.observations.stations))

    def test_reexport_keeps_original_calibration_assets(self):
        run = open_run(self.fit_zip)
        target = self.root / "reexport.zip"
        export_run(run, target)
        reopened = open_run(target)
        self.assertEqual(reopened.calibration_assets, run.calibration_assets)

    def test_old_cli_grid_bundle_reopens_without_solver(self):
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(self.flat_zip) as archive:
                archive.extractall(tmp)  # Own trusted archive, inside fresh temp.
            with patch("subsidence.workspace.solve_flat", side_effect=AssertionError("Unexpected solve")):
                run = open_run(Path(tmp) / "grid")
            assert_array_equal(run.displacement.displacement_m, self.flat.displacement.displacement_m)
            self.assertEqual(run.document.profiles, self.flat_doc.profiles)

    def test_archive_refuses_overwrite_and_export_of_stale_parameters_or_observations(self):
        with self.assertRaises(ValidationError):
            export_run(self.flat, self.flat_zip)
        stale = replace(self.flat, document=replace(self.flat_doc, model=FlatModel(2, 20)))
        with self.assertRaises(ValidationError):
            export_run(stale, self.root / "stale.zip")
        stale = replace(self.flat, document=replace(self.flat_doc, observations=self.fit_doc.observations))
        with self.assertRaises(ValidationError):
            export_run(stale, self.root / "stale_observations.zip")

    def test_hash_mismatch_is_rejected(self):
        target = self.root / "corrupt.zip"
        rewrite_archive(self.flat_zip, target, {"desktop_project.json": b"{}"})
        with self.assertRaisesRegex(ValidationError, "integrity"):
            open_run(target)

    def test_unsafe_paths_duplicate_entries_and_archive_size_are_rejected(self):
        for i, name in enumerate(("../outside.txt", "C:/outside.txt", "/outside.txt", "grid\\outside.txt")):
            target = self.root / f"unsafe{i}.zip"
            rewrite_archive(self.flat_zip, target, {name: b"bad"}, refresh_hashes=True)
            with self.subTest(name=name), self.assertRaisesRegex(ValidationError, "Unsafe|manifest"):
                open_run(target)
        target = self.root / "duplicate.zip"
        rewrite_archive(self.flat_zip, target, {})
        with zipfile.ZipFile(target, "a") as archive, warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            archive.writestr("manifest.json", b"{}")
        with self.assertRaisesRegex(ValidationError, "duplicate"):
            open_run(target)
        with patch("subsidence.workspace.MAX_ARCHIVE_BYTES", 1), self.assertRaisesRegex(ValidationError, "limits"):
            open_run(self.flat_zip)

    def test_saved_strain_inconsistency_rejected_even_with_updated_hash(self):
        with zipfile.ZipFile(self.flat_zip) as archive:
            with np.load(io.BytesIO(archive.read("grid/strain.npz")), allow_pickle=False) as data:
                values = dict(data)
        values["ex"] = values["ex"] + 1
        buffer = io.BytesIO()
        np.savez_compressed(buffer, **values)
        target = self.root / "bad_strain.zip"
        rewrite_archive(self.flat_zip, target, {"grid/strain.npz": buffer.getvalue()}, refresh_hashes=True)
        with self.assertRaisesRegex(ValidationError, "strain"):
            open_run(target)

    def test_mismatched_document_and_grid_rejected(self):
        document = self.flat_doc.to_dict()
        document["model"]["smax_m"] = 3
        target = self.root / "bad_document.zip"
        rewrite_archive(self.flat_zip, target, {"desktop_project.json": json.dumps(document).encode()}, refresh_hashes=True)
        with self.assertRaisesRegex(ValidationError, "settings differ"):
            open_run(target)

    def test_invalid_document_schema_display_fields_and_embedded_data_rejected(self):
        for changes in ({"schema_version": True}, {"extra": 1}, {"selected_field": "Unknown"}, {"colormap": "unknown"}, {"observations": {"csv_base64": "!", "metadata_base64": "!"}}, {"profiles": "bad"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                ProjectDocument.from_dict(self.flat_doc.to_dict() | changes)

    def test_invalid_grid_and_profile_rejected_before_solving(self):
        from subsidence.config import Spacing
        documents = [replace(self.flat_doc, project=replace(self.flat_doc.project, surface_grid=Spacing(1000, 800))), replace(self.flat_doc, profiles=(ProfileLine("Outside", (-501, 0), (0, 0)),))]
        for doc in documents:
            with patch("subsidence.workspace.solve_flat") as solver, self.assertRaises(ValidationError):
                compute_document(doc)
            solver.assert_not_called()

    def test_cache_matching_ignores_visual_changes_but_tracks_physics_and_observations(self):
        changed = replace(self.flat_doc, selected_field="Ey", colormap="coolwarm", profiles=())
        self.assertTrue(self.flat.matches(changed))
        self.assertFalse(self.flat.matches(replace(changed, model=FlatModel(2, 20))))
        self.assertFalse(self.flat.matches(replace(changed, observations=self.fit_doc.observations)))

    def test_gui_cli_dispatch(self):
        with patch("subsidence.desktop.launch") as launch, redirect_stdout(io.StringIO()):
            self.assertEqual(main(["gui", "--project", "test.json"]), 0)
        launch.assert_called_once_with("test.json")


class DesktopWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import tkinter as tk
        except ImportError as exc:
            raise unittest.SkipTest(f"Tk display unavailable: {exc}")
        from subsidence.desktop import DesktopApp, example_document
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"Tk display unavailable: {exc}")
        cls.root.withdraw()
        cls.app = DesktopApp(cls.root)
        cls.temporary = tempfile.TemporaryDirectory()
        cls.path = Path(cls.temporary.name)
        cls.flat = compute_document(example_document("Synthetic flat"))
        cls.errors = []
        cls.root.report_callback_exception = lambda *args: cls.errors.append(args)

    @classmethod
    def tearDownClass(cls):
        cls.app.close()
        cls.temporary.cleanup()

    def setUp(self):
        from subsidence.desktop import example_document
        self.app.set_document(example_document("Synthetic flat"))
        self.errors.clear()

    def wait_for_job(self):
        deadline = time.monotonic() + 40
        while self.app.busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertFalse(self.app.busy, "Desktop operation timed out")
        self.assertFalse(self.errors)
        self.assertTrue(gc.isenabled())

    def test_forms_reproduce_loaded_example_and_support_rectangles(self):
        self.assertEqual(self.app.collect_document().to_dict(), self.flat.document.to_dict())
        for variable, value in zip(self.app.rect_values, (210, 250, -20, 20)):
            variable.set(str(value))
        self.app.add_rectangle()
        self.assertEqual(len(self.app.collect_document().project.extraction_rectangles), 2)
        self.app.rectangles.selection_set(self.app.rectangles.get_children()[-1])
        self.app.remove_rectangle()
        self.assertEqual(len(self.app.collect_document().project.extraction_rectangles), 1)

    def test_background_compute_restores_controls_and_matches_core(self):
        with patch("subsidence.desktop.messagebox.showerror") as error:
            self.app.compute()
            self.assertTrue(self.app.busy)
            self.wait_for_job()
            error.assert_not_called()
        assert_array_equal(self.app.run.displacement.displacement_m, self.flat.displacement.displacement_m)

    def test_map_and_profile_ui_changes_never_call_solver(self):
        self.app.show_run(replace(self.flat))
        with patch("subsidence.workspace.solve_flat", side_effect=AssertionError("Unexpected solve")):
            self.app.field.set("Ey")
            self.app.colormap.set("plasma")
            self.app.draw_map()
            for var, value in zip(self.app.profile_vars, ("Oblique UI", "-300", "-200", "300", "200", "51")):
                var.set(value)
            self.app.add_profile()
            self.app.profile_field.set("Ex")
            self.app.draw_profile()
        self.assertIn("mm/m", self.app.stats.get())
        self.assertEqual(self.app.profile_lines[-1].name, "Oblique UI")

    def test_physics_edits_cannot_export_stale_arrays(self):
        self.app.show_run(replace(self.flat))
        self.app.variables["amplitude"].set("2")
        with self.assertRaisesRegex(ValidationError, "changed"):
            self.app._ready_run()

    def test_export_and_open_run_through_ui_actions_without_recomputing(self):
        self.app.show_run(replace(self.flat))
        path = self.path / "ui_run.zip"
        with patch("subsidence.desktop.messagebox.showerror") as error, patch("subsidence.workspace.solve_flat", side_effect=AssertionError("Unexpected solve")):
            with patch("subsidence.desktop.filedialog.asksaveasfilename", return_value=str(path)):
                self.app.export_archive()
                self.wait_for_job()
            self.app.load_example("Synthetic inclined")
            with patch("subsidence.desktop.filedialog.askopenfilename", return_value=str(path)):
                self.app.open_archive()
                self.wait_for_job()
            error.assert_not_called()
        assert_array_equal(self.app.run.displacement.displacement_m, self.flat.displacement.displacement_m)
        self.assertEqual(self.app.variables["model"].get(), "Flat")

    def test_loading_and_clearing_observations_preserves_raw_evidence(self):
        _, _, _, data = write_synthetic_inputs(self.path / "ui_station_inputs")
        root = self.path / "ui_station_inputs"
        with patch("subsidence.desktop.filedialog.askopenfilename", side_effect=[str(root / "observations.csv"), str(root / "metadata.json")]):
            self.app.load_stations()
        self.assertEqual(self.app.observations.raw_csv, data.raw_csv)
        self.assertIn("synthetic_verification", self.app.station_info.get())
        self.app.clear_stations()
        self.assertIsNone(self.app.observations)

    def test_save_and_open_project_through_dialog_actions(self):
        path = self.path / "ui_project.json"
        self.app.variables["name"].set("UI saved project")
        with patch("subsidence.desktop.filedialog.asksaveasfilename", return_value=str(path)):
            self.app.save_project()
        self.app.variables["name"].set("Unsaved edit")
        with patch("subsidence.desktop.filedialog.askopenfilename", return_value=str(path)):
            self.app.open_project()
        self.assertEqual(self.app.variables["name"].get(), "UI saved project")

    def test_native_project_and_model_json_import(self):
        base = Path(__file__).resolve().parents[1] / "examples"
        with patch("subsidence.desktop.filedialog.askopenfilename", side_effect=[str(base / "synthetic_inclined.json"), str(base / "inclined_model.json")]):
            self.app.open_project()
        self.assertEqual(self.app.variables["model"].get(), "Inclined v1")
        self.assertGreater(self.app.collect_document().project.seam.dip_deg, 9)

    def test_calibration_demo_runs_from_forms_and_displays_held_out_metrics(self):
        self.app.load_example("Synthetic calibration demo")
        with patch("subsidence.desktop.messagebox.showerror") as error:
            self.app.calibrate()
            self.wait_for_job()
            error.assert_not_called()
        self.assertLess(abs(self.app.run.document.model.p_m - 1.2), 0.002)
        self.assertEqual(len(self.app.station_metrics.get_children()), 2)
        self.assertIn("HELD-OUT TESTING", self.app.calibration_text.get("1.0", "end"))
        self.assertIn("synthetic_verification", self.app.station_info.get())

    def test_failed_calibration_shows_diagnostics_without_creating_fitted_run(self):
        self.app.load_example("Synthetic calibration demo")
        self.app.variables["max_nfev"].set("1")
        with patch("subsidence.desktop.messagebox.showerror") as error:
            self.app.calibrate()
            self.wait_for_job()
            error.assert_called_once()
        self.assertIsNone(self.app.run)
        self.assertIn("No converged start", self.app.calibration_text.get("1.0", "end"))

    def test_invalid_geometry_reports_error_before_starting_worker(self):
        self.app.variables["source_dx"].set("0")
        with patch("subsidence.desktop.messagebox.showerror") as error:
            self.app._guard(self.app.compute)
            error.assert_called_once()
        self.assertFalse(self.app.busy)


if __name__ == "__main__":
    unittest.main()
