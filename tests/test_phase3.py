"""Manufactured derivatives and independent profile interpolation checks."""

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

from subsidence import FlatModel, ProfileLine, Rectangle, ValidationError, build_surface_grid, horizontal_strain, load_profiles, load_project, sample_profile, save_profiles, solve_flat
from subsidence.cli import main
from subsidence.config import Spacing
from subsidence.mesh import SurfaceGrid
from subsidence.phase3_results import export_deformation, export_profiles, load_grid_run
from subsidence.phase3_verification import bilinear_displacement, manufactured_surface, run_deformation_verification
from subsidence.reference import analytical_flat_strain
from subsidence.results import export_displacements


ROOT = Path(__file__).resolve().parents[1]


def fields():
    surface = manufactured_surface()
    x, y = surface.xyz_m[..., 0], surface.xyz_m[..., 1]
    displacement = bilinear_displacement(x, y)
    return surface, displacement, horizontal_strain(surface, displacement)


def small_project():
    p = load_project(ROOT / "examples/synthetic_flat.json")
    return replace(p, field=Rectangle(-60, 60, -50, 50), extraction_rectangles=(Rectangle(-20, 20, -10, 10),))


class DerivativeTests(unittest.TestCase):
    def test_constant_displacement_zero_strain(self):
        surface = manufactured_surface()
        displacement = np.broadcast_to([3.0, -2.0, 50.0], surface.xyz_m.shape)
        strain = horizontal_strain(surface, displacement)
        assert_allclose(strain.ex, 0, atol=1e-14)
        assert_allclose(strain.ey, 0, atol=1e-14)

    def test_cross_axis_fields_do_not_produce_normal_strain(self):
        surface = manufactured_surface()
        x, y = surface.xyz_m[..., 0], surface.xyz_m[..., 1]
        displacement = np.stack([7 * y, -9 * x, x + y], axis=-1)
        strain = horizontal_strain(surface, displacement)
        assert_allclose(strain.ex, 0, atol=1e-14)
        assert_allclose(strain.ey, 0, atol=1e-14)

    def test_affine_known_strain_units_signs_and_boundary_mask(self):
        surface = manufactured_surface()
        x, y = surface.xyz_m[..., 0], surface.xyz_m[..., 1]
        displacement = np.stack([0.002 * x + y, -0.003 * y + x, x * 0], axis=-1)
        strain = horizontal_strain(surface, displacement)
        assert_allclose(strain.ex, 0.002, atol=1e-14)
        assert_allclose(strain.ey, -0.003, atol=1e-14)
        assert_allclose(strain.ex_mm_per_m, 2, atol=1e-11)
        assert_allclose(strain.ey_mm_per_m, -3, atol=1e-11)
        self.assertEqual(strain.boundary_mask.sum(), 14)
        self.assertFalse(strain.boundary_mask[1:-1, 1:-1].any())
        self.assertIn("one-sided", strain.metadata["boundary_policy"])

    def test_quadratic_is_exact_on_nonuniform_grid_including_boundaries(self):
        surface = manufactured_surface()
        x, y = surface.xyz_m[..., 0], surface.xyz_m[..., 1]
        displacement = np.stack([x**2 + 2 * x * y, 3 * y**2 - x * y, x * 0], axis=-1)
        strain = horizontal_strain(surface, displacement)
        assert_allclose(strain.ex, 2 * x + 2 * y, atol=1e-13)
        assert_allclose(strain.ey, 6 * y - x, atol=1e-13)

    def test_partial_boundary_cells_use_actual_center_spacing(self):
        p = replace(small_project(), field=Rectangle(0, 3.5, 0, 3.2), surface_grid=Spacing(1, 1))
        surface = build_surface_grid(p)
        x, y = surface.xyz_m[..., 0], surface.xyz_m[..., 1]
        strain = horizontal_strain(surface, np.stack([x**2, y**2, x * 0], axis=-1))
        assert_allclose(strain.ex, 2 * x, atol=1e-13)
        assert_allclose(strain.ey, 2 * y, atol=1e-13)

    def test_three_by_three_is_smallest_supported_strain_grid(self):
        p = replace(small_project(), field=Rectangle(0, 3, 0, 3), surface_grid=Spacing(1, 1))
        surface = build_surface_grid(p)
        strain = horizontal_strain(surface, np.zeros_like(surface.xyz_m))
        self.assertEqual(strain.metadata["interior_cell_count"], 1)
        self.assertEqual(strain.metadata["boundary_cell_count"], 8)
        thin = replace(p, field=Rectangle(0, 2, 0, 3))
        surface = build_surface_grid(thin)
        with self.assertRaisesRegex(ValidationError, "at least 3"):
            horizontal_strain(surface, np.zeros_like(surface.xyz_m))

    def test_nonfinite_and_wrong_displacement_shapes_are_rejected(self):
        surface = manufactured_surface()
        for value in (np.zeros((4, 5)), np.full(surface.xyz_m.shape, np.nan), np.zeros(surface.xyz_m.shape, dtype=bool)):
            with self.subTest(shape=value.shape), self.assertRaises(ValidationError):
                horizontal_strain(surface, value)

    def test_curvilinear_and_invalid_edges_are_rejected(self):
        surface = manufactured_surface()
        changed = surface.xyz_m.copy()
        changed[1, 1, 0] += 0.1
        with self.assertRaisesRegex(ValidationError, "rectilinear"):
            horizontal_strain(replace(surface, xyz_m=changed), np.zeros_like(changed))
        with self.assertRaisesRegex(ValidationError, "edges"):
            horizontal_strain(replace(surface, x_edges_m=surface.x_edges_m[::-1]), np.zeros_like(surface.xyz_m))

    def test_zero_extraction_and_zero_amplitude_have_zero_strains(self):
        p, model = small_project(), FlatModel(1, 20)
        surface = build_surface_grid(p)
        for changed, parameters in ((replace(p, extraction_rectangles=()), model), (p, FlatModel(0, 20))):
            result = solve_flat(changed, parameters, surface.xyz_m)
            strain = horizontal_strain(surface, result.displacement_m)
            assert_array_equal(strain.ex, np.zeros(strain.ex.shape))
            assert_array_equal(strain.ey, np.zeros(strain.ey.shape))


class ProfileTests(unittest.TestCase):
    def test_profile_definition_round_trip_and_three_examples(self):
        lines = load_profiles(ROOT / "examples/profiles.json")
        self.assertEqual(len(lines), 3)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profiles.json"
            save_profiles(lines, path)
            self.assertEqual(load_profiles(path), lines)

    def test_invalid_line_definitions(self):
        bad = [dict(name=""), dict(end_xy_m=(0, 0)), dict(start_xy_m=(float("nan"), 0)), dict(start_xy_m=(True, 0)), dict(sample_count=1), dict(sample_count=True), dict(sample_count=2.5), dict(sample_count=1000001)]
        for change in bad:
            values = dict(name="line", start_xy_m=(0, 0), end_xy_m=(1, 1), sample_count=3) | change
            with self.subTest(change=change), self.assertRaises(ValidationError):
                ProfileLine(**values)

    def test_profile_schema_rejects_units_duplicates_and_unknown_keys(self):
        base = {"schema_version": 1, "units": {"length": "m"}, "profiles": [ProfileLine("a", (0, 0), (1, 1)).to_dict()]}
        variants = [base | {"units": {"length": "ft"}}, base | {"schema_version": True}, base | {"profiles": base["profiles"] * 2}, base | {"profiles": []}, base | {"extra": 1}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profiles.json"
            for data in variants:
                path.write_text(json.dumps(data), encoding="utf-8")
                with self.subTest(data=data), self.assertRaises(ValidationError):
                    load_profiles(path)

    def test_oblique_profile_matches_independent_bilinear_field_values(self):
        surface, displacement, strain = fields()
        line = ProfileLine("oblique", (-5, -4), (6, 3.5), 91)
        sampled = sample_profile(surface, displacement, strain, line)
        x, y = sampled.xyz_m[:, 0], sampled.xyz_m[:, 1]
        assert_allclose(sampled.displacement_m, bilinear_displacement(x, y), atol=1e-14)
        assert_allclose(sampled.ex, 0.002 + 0.001 * y, atol=1e-14)
        assert_allclose(sampled.ey, -0.003 - 0.002 * x, atol=1e-14)
        self.assertEqual(sampled.distance_m[0], 0)
        self.assertEqual(sampled.distance_m[-1], math.hypot(11, 7.5))
        self.assertIn("no directional projection", sampled.metadata["strain_components"])

    def test_horizontal_vertical_and_reversed_lines_preserve_order(self):
        surface, displacement, strain = fields()
        for start, end in (((-5, 1), (6, 1)), ((0, -4), (0, 3.5)), ((-5, -4), (6, 3.5))):
            forward = sample_profile(surface, displacement, strain, ProfileLine("forward", start, end, 17))
            backward = sample_profile(surface, displacement, strain, ProfileLine("backward", end, start, 17))
            assert_allclose(forward.displacement_m, backward.displacement_m[::-1], atol=1e-14)
            assert_allclose(forward.ex, backward.ex[::-1], atol=1e-14)
            assert_allclose(forward.distance_m, backward.distance_m, atol=1e-14)

    def test_exact_grid_centers_reproduce_original_values(self):
        surface, displacement, strain = fields()
        for row in range(surface.xyz_m.shape[0]):
            for col in range(surface.xyz_m.shape[1] - 1):
                line = ProfileLine("nodes", tuple(surface.xyz_m[row, col, :2]), tuple(surface.xyz_m[row, col + 1, :2]), 2)
                sampled = sample_profile(surface, displacement, strain, line)
                assert_array_equal(sampled.displacement_m, displacement[row, col:col + 2])
                assert_array_equal(sampled.ex, strain.ex[row, col:col + 2])

    def test_boundary_influence_ignores_zero_weight_neighbors(self):
        surface, displacement, strain = fields()
        interior = ProfileLine("interior nodes", (-2.5, -1.5), (2.5, -1.5), 3)
        self.assertFalse(sample_profile(surface, displacement, strain, interior).boundary_influenced.any())
        edge = ProfileLine("edge", (-5, -4), (6, -4), 10)
        self.assertTrue(sample_profile(surface, displacement, strain, edge).boundary_influenced.all())

    def test_outer_physical_edges_and_outside_points_do_not_extrapolate(self):
        surface, displacement, strain = fields()
        for start, end in (((-6, 0), (0, 0)), ((0, 0), (7, 0)), ((0, -4.1), (0, 0)), ((0, 0), (0, 3.6))):
            with self.subTest(start=start), self.assertRaisesRegex(ValidationError, "Extrapolation is disabled"):
                sample_profile(surface, displacement, strain, ProfileLine("outside", start, end))

    def test_mismatched_strain_grid_and_displacement_are_rejected(self):
        surface, displacement, strain = fields()
        line = ProfileLine("test", (0, 0), (1, 1))
        with self.assertRaisesRegex(ValidationError, "different displacement"):
            sample_profile(surface, displacement + 1, strain, line)
        with self.assertRaisesRegex(ValidationError, "coordinates"):
            sample_profile(surface, displacement, replace(strain, xyz_m=strain.xyz_m + 1), line)


class ReferenceAndAcceptanceTests(unittest.TestCase):
    def test_analytical_strain_matches_independent_gauss_legendre_integral(self):
        p = small_project()
        model = FlatModel(1, 20)
        points = np.array([[0, 0, 0], [40, 25, 0], [-100, -60, 0]])
        nodes, weights = np.polynomial.legendre.leggauss(40)
        x, y = np.meshgrid(20 * nodes, 10 * nodes, indexing="xy")
        areas = np.outer(weights, weights) * 20 * 10
        radius = 400 * math.tan(math.radians(20))
        expected = []
        for px, py, _ in points:
            dx, dy = x - px, y - py
            ds = np.exp(-math.pi * (dx**2 + dy**2) / radius**2) / radius**2 * areas
            expected.append([np.sum(ds * (2 * math.pi * dx**2 / radius**2 - 1) / 400), np.sum(ds * (2 * math.pi * dy**2 / radius**2 - 1) / 400)])
        assert_allclose(analytical_flat_strain(p, model, points), expected, rtol=1e-13, atol=1e-17)

    def test_manufactured_and_direct_solver_acceptance_report(self):
        report = run_deformation_verification()
        self.assertTrue(report["passed"], report["checks"])
        self.assertEqual(len(report["checks"]), 9)
        errors = np.array([row["max_all_strain_error"] for row in report["strain_convergence"]])
        self.assertTrue(np.all(np.diff(errors) < 0))
        self.assertTrue(np.all(errors[:-1] / errors[1:] > 3.5))


class Phase3ExportAndCliTests(unittest.TestCase):
    def test_full_bundle_reopens_with_strain_units_and_profiles(self):
        p, model = small_project(), FlatModel(1, 20)
        surface = build_surface_grid(p)
        result = solve_flat(p, model, surface.xyz_m)
        strain = horizontal_strain(surface, result.displacement_m)
        line = ProfileLine("Custom / name is not a path", (-40, 0), (40, 0), 17)
        profile = sample_profile(surface, result.displacement_m, strain, line)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "run"
            summary = export_deformation(p, model, surface, result, strain, output, profiles=(profile,))
            self.assertEqual(summary["profile_count"], 1)
            self.assertIn("interior_only", summary["statistics_dimensionless"]["ex"])
            with np.load(output / "strain.npz", allow_pickle=False) as arrays:
                assert_array_equal(arrays["ex"], strain.ex)
                assert_array_equal(arrays["ey_mm_per_m"], strain.ey * 1000)
                assert_array_equal(arrays["boundary_mask"], strain.boundary_mask)
            with np.load(output / "profiles/profile_001.npz", allow_pickle=False) as arrays:
                assert_array_equal(arrays["displacement_m"], profile.displacement_m)
                assert_array_equal(arrays["ex"], profile.ex)
            saved = load_grid_run(output)
            assert_array_equal(saved.displacement_m, result.displacement_m)
            self.assertEqual(len((output / "strain.csv").read_text().splitlines()), 31)
            self.assertEqual(len((output / "profiles/profile_001.csv").read_text().splitlines()), 18)
            ET.parse(output / "strain_maps.svg")
            ET.parse(output / "profiles/profile_001.svg")
            with self.assertRaisesRegex(ValidationError, "empty"):
                export_deformation(p, model, surface, result, strain, output)

    def test_export_rejects_changed_strain_and_profile_source(self):
        p, model = small_project(), FlatModel(1, 20)
        surface = build_surface_grid(p)
        result = solve_flat(p, model, surface.xyz_m)
        wrong = horizontal_strain(surface, result.displacement_m + 1)
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(ValidationError, "does not match"):
            export_deformation(p, model, surface, result, wrong, tmp)

    def test_saved_phase2_run_can_be_profiled_without_influence_solver(self):
        p, model = small_project(), FlatModel(1, 20)
        surface = build_surface_grid(p)
        result = solve_flat(p, model, surface.xyz_m)
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            run = Path(tmp) / "phase2"
            export_displacements(p, model, surface, result, run)
            definition = Path(tmp) / "profiles.json"
            save_profiles((ProfileLine("new", (-40, 0), (40, 0), 11),), definition)
            with patch("subsidence.cli.solve_flat", side_effect=AssertionError("Solver must not rerun")), patch("subsidence.solver.solve_flat", side_effect=AssertionError("Solver must not rerun")):
                self.assertEqual(main(["sample-profiles", str(run), "--profiles", str(definition), "--output", str(Path(tmp) / "profiles")]), 0)
            metadata_path = run / "result_summary.json"
            metadata = json.loads(metadata_path.read_text())
            del metadata["project"]  # Original early Phase 2 example compatibility.
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            self.assertEqual(load_grid_run(run).displacement_m.shape, surface.xyz_m.shape)

    def test_saved_input_and_array_mismatches_are_rejected(self):
        p, model = small_project(), FlatModel(1, 20)
        surface = build_surface_grid(p)
        result = solve_flat(p, model, surface.xyz_m)
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            export_displacements(p, model, surface, result, run)
            model_file = run / "model.json"
            original = model_file.read_text()
            data = json.loads(original)
            data["smax_m"] = 2
            model_file.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, "recorded prediction"):
                load_grid_run(run)
            model_file.write_text(original, encoding="utf-8")
            np.savez_compressed(run / "displacement.npz", xyz_m=surface.xyz_m + 1, displacement_m=result.displacement_m)
            with self.assertRaisesRegex(ValidationError, "coordinates differ"):
                load_grid_run(run)

    def test_cli_deform_flat_with_and_without_profiles_and_invalid_line(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            arguments = ["deform-flat", str(ROOT / "examples/synthetic_flat.json"), "--model", str(ROOT / "examples/flat_model.json")]
            self.assertEqual(main(arguments + ["--profiles", str(ROOT / "examples/profiles.json"), "--output", str(Path(tmp) / "full")]), 0)
            self.assertEqual(main(arguments + ["--output", str(Path(tmp) / "strain_only")]), 0)
            bad = Path(tmp) / "bad.json"
            save_profiles((ProfileLine("outside", (-500, 0), (500, 0)),), bad)
            with redirect_stderr(io.StringIO()) as error:
                self.assertEqual(main(arguments + ["--profiles", str(bad), "--output", str(Path(tmp) / "invalid")]), 2)
            self.assertIn("Extrapolation is disabled", error.getvalue())
            self.assertFalse((Path(tmp) / "invalid").exists())

    def test_cli_verification_exports_numerical_evidence(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            target = Path(tmp) / "verification"
            self.assertEqual(main(["verify-deformation", "--output", str(target)]), 0)
            self.assertTrue(json.loads((target / "verification.json").read_text())["passed"])
            self.assertTrue((target / "strain_convergence.png").exists())
            self.assertTrue((target / "verification.md").exists())


if __name__ == "__main__":
    unittest.main()
