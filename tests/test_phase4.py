"""Inclined geometry/integration checks, not field validation."""

from contextlib import redirect_stderr, redirect_stdout
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

from subsidence import FlatModel, InclinedModel, ProfileLine, Rectangle, SeamFrame, SeamPlane, ValidationError, build_surface_grid, horizontal_strain, load_model, load_project, sample_profile, save_model, solve_flat, solve_inclined
from subsidence.cli import main
from subsidence.config import Spacing, load_flat_model
from subsidence.inclined_reference import quadrature_inclined_displacement
from subsidence.phase3_results import export_deformation, load_grid_run
from subsidence.phase4_verification import inclined_benchmark, normal_at_dip, quarter_turn, run_inclined_verification
from subsidence.reference import analytical_flat_displacement
from subsidence.results import export_displacements


ROOT = Path(__file__).resolve().parents[1]


def small_project(dip=10):
    return replace(inclined_benchmark(dip), field=Rectangle(-60, 60, -50, 50), extraction_rectangles=(Rectangle(-20, 20, -10, 10),))


class ModelAndFrameTests(unittest.TestCase):
    def test_strict_inclined_model_round_trip_and_flat_compatibility(self):
        model = load_model(ROOT / "examples/inclined_model.json")
        self.assertEqual(model, InclinedModel(1, 20))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model.json"
            save_model(model, path)
            self.assertEqual(load_model(path), model)
        self.assertEqual(load_model(ROOT / "examples/flat_model.json"), FlatModel(1, 20))
        with self.assertRaises(ValidationError):
            load_flat_model(ROOT / "examples/inclined_model.json")

    def test_invalid_parameters_and_ambiguous_conventions_are_rejected(self):
        for changes in ({"p_m": -1}, {"p_m": True}, {"p_m": float("nan")}, {"influence_angle_deg": 90}, {"depth_convention": "vertical_depth"}, {"area_measure": "plan_area"}, {"amplitude_convention": "p_equals_smax"}, {"kernel_support": "radius_R"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                InclinedModel(**({"p_m": 1, "influence_angle_deg": 20} | changes))
        for change in ({"schema_version": True}, {"smax_m": 1}, {"units": {"length": "feet"}}, {"model": "other"}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                InclinedModel.from_dict(InclinedModel(1, 20).to_dict() | change)

    def test_basis_is_identity_at_zero_and_right_handed_orthonormal(self):
        assert_array_equal(SeamFrame(inclined_benchmark(0).seam).basis, np.eye(3))
        for normal in ((0.1, 0.15, 1), (-0.1, -0.15, 1), (0.1, -0.15, 1), normal_at_dip(12)):
            frame = SeamFrame(SeamPlane((3, -4, -400), normal))
            assert_allclose(frame.basis.T @ frame.basis, np.eye(3), atol=1e-15)
            assert_allclose(frame.basis[:, 2], frame.seam.unit_normal, atol=1e-15)
            self.assertAlmostEqual(np.linalg.det(frame.basis), 1, places=14)

    def test_points_and_vectors_round_trip_without_vector_translation(self):
        frame = SeamFrame(SeamPlane((120, 50, -400), (0.1, -0.12, 1)))
        xyz = np.random.default_rng(29).normal(size=(3, 7, 3)) * 500
        assert_allclose(frame.points_to_global(frame.points_to_local(xyz)), xyz, atol=5e-13)
        assert_allclose(frame.vectors_to_global(frame.vectors_to_local(xyz)), xyz, atol=5e-13)
        assert_array_equal(frame.vectors_to_global([0, 0, 0]), [0, 0, 0])
        assert_array_equal(frame.points_to_global([0, 0, 0]), frame.seam.reference_xyz_m)

    def test_invalid_coordinate_and_vector_inputs(self):
        frame = SeamFrame(inclined_benchmark().seam)
        for values in ([0, 0], [0, 0, float("inf")], [True, False, False], ["0", "1", "2"]):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                frame.points_to_local(values)


class InclinedSolverTests(unittest.TestCase):
    def test_zero_dip_all_fields_and_profiles_reduce_to_flat_case(self):
        p = small_project(0)
        surface = build_surface_grid(p)
        flat = solve_flat(p, FlatModel(1, 20), surface.xyz_m)
        inclined = solve_inclined(p, InclinedModel(1, 20), surface.xyz_m)
        assert_allclose(inclined.displacement_m, flat.displacement_m, atol=1e-15)
        a, b = horizontal_strain(surface, flat.displacement_m), horizontal_strain(surface, inclined.displacement_m)
        assert_allclose(a.ex, b.ex, atol=1e-16)
        assert_allclose(a.ey, b.ey, atol=1e-16)
        line = ProfileLine("limit", (-40, 0), (40, 0), 19)
        pa = sample_profile(surface, flat.displacement_m, a, line)
        pb = sample_profile(surface, inclined.displacement_m, b, line)
        assert_allclose(pa.displacement_m, pb.displacement_m, atol=1e-15)
        assert_allclose(pa.ex, pb.ex, atol=1e-16)

    def test_transparent_one_cell_on_normal_ray(self):
        normal = normal_at_dip(10)
        p = replace(small_project(), seam=SeamPlane((0, 0, -100), normal), extraction_rectangles=(Rectangle(-1, 1, -1, 1),), source_mesh=Spacing(2, 2))
        point = [[0, 100 * math.tan(math.radians(10)), 0]]
        result = solve_inclined(p, InclinedModel(2, 45), point)
        # Local amplitude 2/nz; seam area 4/nz; h=100/nz; R=h.
        local_weight = 8 / 10000
        assert_allclose(result.displacement_m[0], -local_weight * np.array(normal), rtol=2e-14, atol=1e-18)

    def test_one_cell_matches_independent_global_vector_formula(self):
        p = replace(small_project(), extraction_rectangles=(Rectangle(-1, 1, -1, 1),), source_mesh=Spacing(2, 2))
        model, points = InclinedModel(1.3, 20), np.array([[10, 30, 0], [-20, -50, 0]], dtype=float)
        n = np.array(p.seam.unit_normal)
        a = np.array([0, 0, -400])
        expected = []
        for point in points:
            d = point - a
            h = d @ n
            q = d - h * n
            radius = h * math.tan(math.radians(20))
            ds = 1.3 / n[2] * math.exp(-math.pi * (q @ q) / radius**2) / radius**2 * 4 / n[2]
            expected.append(-ds * d / h)
        assert_allclose(solve_inclined(p, model, points).displacement_m, expected, rtol=2e-14, atol=1e-18)

    def test_large_panel_formal_vertical_amplitude_normalization(self):
        p = replace(inclined_benchmark(), extraction_rectangles=(Rectangle(-1000, 1000, -1000, 1000),), source_mesh=Spacing(20, 20))
        n = np.array(p.seam.unit_normal)
        actual = solve_inclined(p, InclinedModel(1.3, 20), [[0, 0, 0]])
        assert_allclose(actual.displacement_m[0], -1.3 * n / n[2], atol=1e-11)

    def test_empty_sources_zero_amplitude_and_empty_evaluation(self):
        p, model = small_project(), InclinedModel(1, 20)
        for project, settings in ((replace(p, extraction_rectangles=()), model), (p, InclinedModel(0, 20))):
            result = solve_inclined(project, settings)
            assert_array_equal(result.displacement_m, np.zeros_like(result.xyz_m))
        empty = solve_inclined(p, model, np.empty((0, 3)))
        self.assertEqual(empty.displacement_m.shape, (0, 3))
        self.assertIsNone(empty.metadata["normal_depth_range_m"])

    def test_dip_scope_and_wrong_model_are_rejected(self):
        self.assertTrue(np.isfinite(solve_inclined(small_project(12), InclinedModel(1, 20)).displacement_m).all())
        with self.assertRaisesRegex(ValidationError, "0 to 12"):
            solve_inclined(small_project(13), InclinedModel(0, 20))
        with self.assertRaisesRegex(ValidationError, "InclinedModel"):
            solve_inclined(small_project(), FlatModel(1, 20))

    def test_nonpositive_normal_depth_rejected_even_without_mining(self):
        p = replace(small_project(), extraction_rectangles=())
        with self.assertRaisesRegex(ValidationError, "positive normal separation"):
            solve_inclined(p, InclinedModel(0, 20), [[0, -3000, 0]])

    def test_shape_order_and_fixed_station_domain_independence(self):
        p, model = small_project(), InclinedModel(1, 20)
        result = solve_inclined(p, model)
        stations = result.xyz_m.reshape(-1, 3)[[0, 7, 29]]
        direct = solve_inclined(p, model, stations)
        assert_allclose(direct.displacement_m, result.displacement_m.reshape(-1, 3)[[0, 7, 29]], atol=1e-15)
        changed = replace(p, field=Rectangle(500, 600, 0, 100), surface_grid=Spacing(1, 2))
        assert_array_equal(solve_inclined(changed, model, stations).displacement_m, direct.displacement_m)

    def test_normal_scaling_sign_and_reference_shift_on_same_plane(self):
        p, model = small_project(), InclinedModel(1, 20)
        points = [[0, 0, 0], [20, 30, 0]]
        expected = solve_inclined(p, model, points).displacement_m
        n = p.seam.normal_xyz
        scaled = replace(p, seam=SeamPlane(p.seam.reference_xyz_m, tuple(-25 * v for v in n)))
        assert_allclose(solve_inclined(scaled, model, points).displacement_m, expected, atol=1e-15)
        reference = (20, 30, float(p.seam.z_at(20, 30)))
        shifted = replace(p, seam=SeamPlane(reference, n))
        assert_allclose(solve_inclined(shifted, model, points).displacement_m, expected, atol=1e-15)

    def test_horizontal_rotation_and_reflection_covariance(self):
        p = replace(small_project(), seam=SeamPlane((0, 0, -400), (0.08, 0.15, 1)))
        model = InclinedModel(1, 20)
        points = np.array([[0, 0, 0], [30, -20, 0], [-40, 40, 0]])
        original = solve_inclined(p, model, points).displacement_m
        rotation = solve_inclined(quarter_turn(p), model, points[:, [1, 0, 2]] * [-1, 1, 1])
        assert_allclose(rotation.displacement_m, original[:, [1, 0, 2]] * [-1, 1, 1], atol=1e-15)
        reflected = replace(p, seam=SeamPlane((0, 0, -400), (-0.08, 0.15, 1)))
        assert_allclose(solve_inclined(reflected, model, points * [-1, 1, 1]).displacement_m, original * [-1, 1, 1], atol=1e-15)

    def test_plan_translation_and_surface_elevation_datum(self):
        p, model = small_project(), InclinedModel(1, 20)
        points = np.array([[0, 0, 0], [30, -20, 0]])
        changed = replace(p, surface_elevation_m=100, seam=SeamPlane((200, -300, -300), p.seam.normal_xyz), extraction_rectangles=(Rectangle(180, 220, -310, -290),))
        assert_allclose(solve_inclined(changed, model, points + [200, -300, 100]).displacement_m, solve_inclined(p, model, points).displacement_m, atol=1e-15)

    def test_overlap_union_amplitude_scaling_and_no_hard_radius_cutoff(self):
        p, model = small_project(), InclinedModel(1, 20)
        points = [[0, 0, 0], [0, 300, 0]]
        base = solve_inclined(p, model, points)
        duplicated = replace(p, extraction_rectangles=p.extraction_rectangles * 2)
        assert_array_equal(solve_inclined(duplicated, model, points).displacement_m, base.displacement_m)
        assert_allclose(solve_inclined(p, InclinedModel(2, 20), points).displacement_m, 2 * base.displacement_m, atol=1e-15)
        self.assertLess(base.uz_m[1], 0)

    def test_chunk_equivalence_and_pair_limits(self):
        p, model = small_project(), InclinedModel(1, 20)
        a = solve_inclined(p, model)
        b = solve_inclined(p, model, observation_chunk_size=3, source_chunk_size=7)
        assert_allclose(a.displacement_m, b.displacement_m, atol=1e-15)
        self.assertEqual(b.metadata["max_block_pairs"], 21)
        for kwargs in ({"observation_chunk_size": 0}, {"source_chunk_size": True}, {"source_chunk_size": 2048, "observation_chunk_size": 2048}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                solve_inclined(p, model, **kwargs)


class IndependentReferenceTests(unittest.TestCase):
    def test_zero_dip_reference_matches_analytical_integral(self):
        p, model = small_project(0), InclinedModel(1, 20)
        points = [[0, 0, 0], [30, -20, 0], [-40, 40, 0]]
        expected = analytical_flat_displacement(p, FlatModel(1, 20), points)
        assert_allclose(quadrature_inclined_displacement(p, model, points), expected, atol=1e-15)

    def test_reference_never_uses_frame_midpoints_or_solver(self):
        p, model = small_project(), InclinedModel(1, 20)
        with patch("subsidence.inclined.solve_inclined", side_effect=AssertionError("Not an independent reference")), patch("subsidence.inclined.build_source_mesh", side_effect=AssertionError("Reference must not mesh")), patch("subsidence.seam_frame.SeamFrame.points_to_local", side_effect=AssertionError("Reference must not use frame")):
            values = quadrature_inclined_displacement(p, model, [[0, 0, 0]])
        self.assertTrue(np.isfinite(values).all())

    def test_inclined_verification_report_and_convergence(self):
        report = run_inclined_verification()
        self.assertTrue(report["passed"], report["checks"])
        self.assertEqual(len(report["checks"]), 27)
        errors = np.array([r["max_component_error_m"] for r in report["convergence"]])
        self.assertTrue(np.all(np.diff(errors) < 0))
        self.assertTrue(np.all(errors[:-1] / errors[1:] > 3.9))


class InclinedExportAndCliTests(unittest.TestCase):
    def test_inclined_bundle_reopens_recomputes_and_preserves_conventions(self):
        p, model = small_project(), InclinedModel(1, 20)
        surface = build_surface_grid(p)
        result = solve_inclined(p, model, surface.xyz_m)
        strain = horizontal_strain(surface, result.displacement_m)
        line = ProfileLine("inclined", (-40, 0), (40, 0), 11)
        profile = sample_profile(surface, result.displacement_m, strain, line)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "bundle"
            export_deformation(p, model, surface, result, strain, output, profiles=(profile,))
            saved = load_grid_run(output)
            self.assertIsInstance(saved.model, InclinedModel)
            assert_array_equal(solve_inclined(saved.project, saved.model, saved.surface.xyz_m).displacement_m, saved.displacement_m)
            summary = json.loads((output / "result_summary.json").read_text())
            self.assertEqual(summary["status"], "inclined_seam_displacement_no_field_validation")
            self.assertEqual(summary["settings"]["area_measure"], "seam_area")
            self.assertAlmostEqual(summary["local_smax_m"], 1 / p.seam.unit_normal[2])
            ET.parse(output / "displacement_maps.svg")
            self.assertTrue((output / "profiles/profile_001.csv").exists())

    def test_cli_solve_and_deform_inclined(self):
        p = small_project()
        from subsidence import save_project
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            project_path = Path(tmp) / "project.json"
            save_project(p, project_path)
            for command in ("solve-inclined", "deform-inclined"):
                output = Path(tmp) / command
                self.assertEqual(main([command, str(project_path), "--model", str(ROOT / "examples/inclined_model.json"), "--output", str(output)]), 0)
                self.assertTrue((output / "displacement.npz").exists())
            with redirect_stderr(io.StringIO()):
                self.assertEqual(main(["solve-inclined", str(project_path), "--model", str(ROOT / "examples/flat_model.json"), "--output", str(Path(tmp) / "bad")]), 2)

    def test_saved_inclined_profiles_do_not_rerun_solver(self):
        p, model = small_project(), InclinedModel(1, 20)
        surface = build_surface_grid(p)
        result = solve_inclined(p, model, surface.xyz_m)
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            output = Path(tmp) / "run"
            export_displacements(p, model, surface, result, output)
            definition = Path(tmp) / "profiles.json"
            from subsidence import save_profiles
            save_profiles((ProfileLine("saved", (-40, 0), (40, 0), 11),), definition)
            with patch("subsidence.inclined.solve_inclined", side_effect=AssertionError("Influence solver rerun")):
                self.assertEqual(main(["sample-profiles", str(output), "--profiles", str(definition), "--output", str(Path(tmp) / "profiles")]), 0)

    def test_report_cli_exports_diagram_and_dip_study(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            output = Path(tmp) / "verification"
            self.assertEqual(main(["verify-inclined", "--output", str(output)]), 0)
            self.assertTrue(json.loads((output / "verification.json").read_text())["passed"])
            for name in ("coordinate_diagram.png", "dip_profiles.png", "reference_points.csv", "verification.md"):
                self.assertTrue((output / name).exists())

    def test_reported_adriyala_geometry_remains_distinct_from_field_validation(self):
        p = load_project(ROOT / "examples/adriyala_geometry.json")
        model = load_model(ROOT / "examples/adriyala_inclined_model.json")
        points = [[1155, 245, 0], [1155, 125, 0], [1155, 365, 0]]
        result = solve_inclined(p, model, points)
        self.assertTrue(np.all(result.uz_m < 0))
        self.assertEqual(result.metadata["evidence"], "reported_geometry")
        self.assertIn("no field validation", result.metadata["validation_scope"])
        self.assertAlmostEqual(model.p_m, 1.3)
        self.assertAlmostEqual(result.metadata["dip_deg"], 10.3046758708, places=8)


if __name__ == "__main__":
    unittest.main()
