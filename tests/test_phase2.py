"""Flat-seam numerical verification; these tests contain no field observations."""

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

from subsidence import FlatModel, Rectangle, SeamPlane, ValidationError, load_flat_model, load_project, save_flat_model, solve_flat
from subsidence.cli import main
from subsidence.config import Project, Spacing
from subsidence.influence import influence_radius_m, stochastic_kernel
from subsidence.mesh import build_surface_grid
from subsidence.reference import analytical_flat_displacement
from subsidence.results import export_displacements
from subsidence.verification import run_flat_verification


ROOT = Path(__file__).resolve().parents[1]


def project(**changes):
    p = Project(
        name="Synthetic flat test", evidence="synthetic_geometry",
        field=Rectangle(-100, 100, -100, 100), seam=SeamPlane((0, 0, -100), (0, 0, 1)),
        extraction_rectangles=(Rectangle(-20, 20, -10, 10),),
        source_mesh=Spacing(2, 2), surface_grid=Spacing(20, 20),
    )
    return replace(p, **changes)


class FlatSettingsAndKernelTests(unittest.TestCase):
    def test_separate_model_file_round_trip(self):
        model = load_flat_model(ROOT / "examples/flat_model.json")
        self.assertEqual(model, FlatModel(1, 20))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model.json"
            save_flat_model(model, path)
            self.assertEqual(load_flat_model(path), model)

    def test_invalid_model_parameters_and_schema(self):
        for amplitude in (-1, float("nan"), float("inf"), True, "1"):
            with self.subTest(amplitude=amplitude), self.assertRaises(ValidationError):
                FlatModel(amplitude, 20)
        for angle in (0, 90, -2, 91, float("nan"), "20", False):
            with self.subTest(angle=angle), self.assertRaises(ValidationError):
                FlatModel(1, angle)
        for change in ({"schema_version": True}, {"model": "inclined"}, {"p_m": 1.3}, {"units": {"angle": "radians"}}, {"kernel_support": "radius_R"}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                FlatModel.from_dict(FlatModel(1, 20).to_dict() | change)

    def test_kernel_value_scale_and_full_support(self):
        radius = influence_radius_m(400, FlatModel(1, 20))
        self.assertAlmostEqual(radius, 400 * math.tan(math.radians(20)))
        values = stochastic_kernel(np.array([0, radius, 2 * radius]), radius)
        assert_allclose(values, np.array([1, math.exp(-math.pi), math.exp(-4 * math.pi)]) / radius**2, rtol=2e-15)
        self.assertGreater(values[2], 0)  # A hard cutoff at R would fail.

    def test_kernel_full_plane_and_circle_mass(self):
        radius = 100
        r = np.linspace(0, 5 * radius, 100001)
        total = np.trapezoid(2 * math.pi * r * stochastic_kernel(r, radius), r)
        self.assertAlmostEqual(total, 1, places=8)
        r = np.linspace(0, radius, 100001)
        inside = np.trapezoid(2 * math.pi * r * stochastic_kernel(r, radius), r)
        self.assertAlmostEqual(inside, 1 - math.exp(-math.pi), places=9)

    def test_invalid_kernel_inputs(self):
        for radius in (0, -1, float("inf"), 1e-300, 1e300):
            with self.subTest(radius=radius), self.assertRaises(ValidationError):
                stochastic_kernel(1, radius)
        for distance in (-1, float("nan"), float("inf")):
            with self.subTest(distance=distance), self.assertRaises(ValidationError):
                stochastic_kernel(distance, 10)


class FlatSolverTests(unittest.TestCase):
    def test_single_source_area_and_displacement_direction(self):
        p = project(extraction_rectangles=(Rectangle(-1, 1, -1, 1),))
        points = [[0, 0, 0], [100, 0, 0], [-100, 0, 0], [0, 100, 0]]
        result = solve_flat(p, FlatModel(2, 45), points)
        center = 2 * 4 / 100**2
        off = center * math.exp(-math.pi)
        expected = [[0, 0, -center], [-off, 0, -off], [off, 0, -off], [0, -off, -off]]
        assert_allclose(result.displacement_m, expected, rtol=2e-15, atol=1e-18)
        self.assertLess(-result.uz_m[0], 2)  # No renormalization of the mined fraction.

    def test_empty_extraction_and_zero_amplitude(self):
        for p, model in ((project(extraction_rectangles=()), FlatModel(1, 20)), (project(), FlatModel(0, 20))):
            with self.subTest(model=model):
                result = solve_flat(p, model)
                assert_array_equal(result.displacement_m, np.zeros_like(result.xyz_m))
                self.assertTrue(np.isfinite(result.displacement_m).all())

    def test_station_grid_single_point_and_empty_shapes(self):
        p, model = project(), FlatModel(1, 20)
        grid = solve_flat(p, model)
        self.assertEqual(grid.displacement_m.shape, (10, 10, 3))
        indices = [0, 8, 31, 99]
        stations = grid.xyz_m.reshape(-1, 3)[indices]
        direct = solve_flat(p, model, stations)
        assert_allclose(direct.displacement_m, grid.displacement_m.reshape(-1, 3)[indices], atol=1e-15)
        self.assertEqual(solve_flat(p, model, [0, 0, 0]).displacement_m.shape, (3,))
        self.assertEqual(solve_flat(p, model, np.empty((0, 3))).displacement_m.shape, (0, 3))

    def test_invalid_evaluation_points(self):
        for points in ([[0, 0]], [[0, 0, 1]], [[float("nan"), 0, 0]], [[True, False, False]], [["0", "0", "0"]], [0, 0, float("inf")]):
            with self.subTest(points=points), self.assertRaises(ValidationError):
                solve_flat(project(), FlatModel(1, 20), points)

    def test_inclined_seams_are_rejected_even_for_zero_amplitude(self):
        p = load_project(ROOT / "examples/adriyala_geometry.json")
        for amplitude in (0, 1):
            with self.assertRaisesRegex(ValidationError, "horizontal seam"):
                solve_flat(p, FlatModel(amplitude, 20), [[0, 0, 0]])

    def test_normal_sign_scale_and_elevation_offset(self):
        p, model = project(), FlatModel(1, 20)
        expected = solve_flat(p, model, [[0, 0, 0], [25, 35, 0]]).displacement_m
        shifted = replace(p, surface_elevation_m=300, seam=SeamPlane((0, 0, 200), (0, 0, -25)))
        assert_allclose(solve_flat(shifted, model, [[0, 0, 300], [25, 35, 300]]).displacement_m, expected, atol=1e-15)

    def test_observation_domain_does_not_change_station_predictions(self):
        p, model = project(), FlatModel(1, 20)
        points = [[0, 0, 0], [40, 60, 0]]
        changed = replace(p, field=Rectangle(500, 600, 500, 600), surface_grid=Spacing(0.7, 0.8))
        assert_array_equal(solve_flat(p, model, points).displacement_m, solve_flat(changed, model, points).displacement_m)

    def test_source_and_observation_translation(self):
        p, model = project(), FlatModel(1, 20)
        points = np.array([[0, 0, 0], [40, 60, 0]], dtype=float)
        shift = np.array([200, -500, 0])
        shifted = replace(p, seam=SeamPlane((200, -500, -100), (0, 0, 1)), extraction_rectangles=(Rectangle(180, 220, -510, -490),))
        assert_allclose(solve_flat(p, model, points).displacement_m, solve_flat(shifted, model, points + shift).displacement_m, atol=1e-15)

    def test_duplicate_and_overlapping_regions_are_not_double_counted(self):
        p, model = project(), FlatModel(1, 20)
        points = [[0, 0, 0], [30, 25, 0]]
        duplicate = replace(p, extraction_rectangles=p.extraction_rectangles * 2)
        overlap = replace(p, extraction_rectangles=(Rectangle(-20, 10, -10, 10), Rectangle(-10, 20, -10, 10)))
        expected = solve_flat(p, model, points).displacement_m
        assert_allclose(solve_flat(duplicate, model, points).displacement_m, expected, atol=1e-15)
        assert_allclose(solve_flat(overlap, model, points).displacement_m, expected, atol=1e-15)

    def test_chunked_pair_arrays_are_bounded_and_results_agree(self):
        p, model = project(), FlatModel(1, 20)
        points = build_surface_grid(p).xyz_m
        expected = solve_flat(p, model, points).displacement_m
        shapes = []

        def observe(distance, radius):
            shapes.append(distance.shape)
            return stochastic_kernel(distance, radius)

        with patch("subsidence.solver.stochastic_kernel", side_effect=observe):
            result = solve_flat(p, model, points, observation_chunk_size=3, source_chunk_size=7)
        self.assertGreater(len(shapes), 1)
        self.assertTrue(all(rows <= 3 and columns <= 7 for rows, columns in shapes))
        self.assertEqual(result.metadata["max_block_pairs"], 21)
        assert_allclose(result.displacement_m, expected, rtol=2e-14, atol=1e-15)

    def test_invalid_chunk_sizes(self):
        for value in (0, -1, True, 1.5):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                solve_flat(project(), FlatModel(1, 20), observation_chunk_size=value)
        with self.assertRaisesRegex(ValidationError, "working-array limit"):
            solve_flat(project(), FlatModel(1, 20), observation_chunk_size=2000, source_chunk_size=2000)


class AnalyticalAndVerificationTests(unittest.TestCase):
    def test_center_integral_has_known_erf_value(self):
        p = project(extraction_rectangles=(Rectangle(-100, 100, -100, 100),))
        exact = analytical_flat_displacement(p, FlatModel(2, 45), [[0, 0, 0]])
        assert_allclose(exact, [[0, 0, -2 * math.erf(math.sqrt(math.pi))**2]], atol=1e-15)

    def test_analytical_all_components_match_independent_gauss_quadrature(self):
        p = project(extraction_rectangles=(Rectangle(-20, 30, -15, 10),))
        model = FlatModel(1.2, 20)
        points = np.array([[0, 0, 0], [40, -25, 0], [-100, 60, 0]])
        # Tensor Gauss-Legendre integration, independently written here. This
        # checks the reference's erf and first-moment factors and signs.
        nodes, weights = np.polynomial.legendre.leggauss(40)
        x, y = np.meshgrid(5 + 25 * nodes, -2.5 + 12.5 * nodes, indexing="xy")
        area_weights = np.outer(weights, weights) * 25 * 12.5
        radius = 100 * math.tan(math.radians(20))
        expected = []
        for px, py, _ in points:
            dx, dy = x - px, y - py
            ds = model.smax_m * np.exp(-math.pi * (dx**2 + dy**2) / radius**2) / radius**2 * area_weights
            expected.append([np.sum(ds * dx / 100), np.sum(ds * dy / 100), -np.sum(ds)])
        assert_allclose(analytical_flat_displacement(p, model, points), expected, rtol=2e-13, atol=1e-15)

    def test_reference_is_independent_of_source_spacing_and_handles_overlap(self):
        p, model = project(), FlatModel(1, 20)
        points = [[0, 0, 0], [10, 25, 0]]
        exact = analytical_flat_displacement(p, model, points)
        fine = replace(p, source_mesh=Spacing(0.1, 0.1))
        assert_array_equal(analytical_flat_displacement(fine, model, points), exact)
        overlaps = replace(p, extraction_rectangles=p.extraction_rectangles * 2)
        assert_array_equal(analytical_flat_displacement(overlaps, model, points), exact)

    def test_reference_preserves_small_nonzero_gaussian_tails(self):
        p = project(extraction_rectangles=(Rectangle(-1, 1, -1, 1),))
        values = analytical_flat_displacement(p, FlatModel(1, 45), [[1000, 0, 0], [-1000, 0, 0]])
        self.assertLess(values[0, 2], 0)
        self.assertLess(values[0, 0], 0)
        assert_allclose(values[0], values[1] * [-1, 1, 1], rtol=1e-13, atol=0)

    def test_repeatable_acceptance_report_passes_with_decreasing_errors(self):
        report = run_flat_verification()
        self.assertTrue(report["passed"], report["checks"])
        self.assertEqual(len(report["checks"]), 11)
        errors = np.array([row["max_component_error_m"] for row in report["convergence"]])
        self.assertTrue(np.all(np.diff(errors) < 0))
        self.assertTrue(np.all(errors[:-1] / errors[1:] > 3.9))


class FlatExportAndCliTests(unittest.TestCase):
    def test_result_bundle_reopens_and_recomputes(self):
        p, model = project(), FlatModel(1, 20)
        surface = build_surface_grid(p)
        result = solve_flat(p, model, surface.xyz_m)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "result"
            summary = export_displacements(p, model, surface, result, target)
            with np.load(target / "displacement.npz", allow_pickle=False) as arrays:
                assert_array_equal(arrays["displacement_m"], result.displacement_m)
                assert_array_equal(arrays["settlement_m"], -arrays["uz_m"])
                recreated = solve_flat(load_project(target / "project.json"), load_flat_model(target / "model.json"), arrays["xyz_m"])
                assert_array_equal(recreated.displacement_m, arrays["displacement_m"])
            self.assertEqual(summary["status"], "flat_seam_displacement_no_field_validation")
            self.assertEqual(len((target / "displacement.csv").read_text().splitlines()), 101)
            ET.parse(target / "displacement_maps.svg")
            self.assertTrue((target / "displacement_maps.png").read_bytes().startswith(b"\x89PNG"))
            with self.assertRaisesRegex(ValidationError, "empty"):
                export_displacements(p, model, surface, result, target)

    def test_export_rejects_mismatched_grid_or_settings(self):
        p, model = project(), FlatModel(1, 20)
        surface = build_surface_grid(p)
        with tempfile.TemporaryDirectory() as tmp:
            result = solve_flat(p, model, [[0, 0, 0]])
            with self.assertRaisesRegex(ValidationError, "supplied surface-grid"):
                export_displacements(p, model, surface, result, tmp)
            result = solve_flat(p, model, surface.xyz_m)
            with self.assertRaisesRegex(ValidationError, "settings"):
                export_displacements(p, FlatModel(2, 20), surface, result, tmp)
            changed = replace(p, extraction_rectangles=())
            with self.assertRaisesRegex(ValidationError, "project"):
                export_displacements(changed, model, surface, result, tmp)

    def test_cli_solve_and_reject_inclined_project(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            output = Path(tmp) / "flat"
            code = main(["solve-flat", str(ROOT / "examples/synthetic_flat.json"), "--model", str(ROOT / "examples/flat_model.json"), "--output", str(output)])
            self.assertEqual(code, 0)
            self.assertTrue((output / "displacement.npz").exists())
            with redirect_stderr(io.StringIO()) as error:
                code = main(["solve-flat", str(ROOT / "examples/adriyala_geometry.json"), "--model", str(ROOT / "examples/flat_model.json"), "--output", str(Path(tmp) / "inclined")])
            self.assertEqual(code, 2)
            self.assertIn("Phase 4", error.getvalue())
            self.assertFalse((Path(tmp) / "inclined").exists())

    def test_cli_verification_exports_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            output = Path(tmp) / "verification"
            self.assertEqual(main(["verify-flat", "--output", str(output)]), 0)
            report = json.loads((output / "verification.json").read_text())
            self.assertTrue(report["passed"])
            self.assertTrue((output / "verification.md").exists())
            self.assertTrue((output / "convergence.png").exists())


if __name__ == "__main__":
    unittest.main()
