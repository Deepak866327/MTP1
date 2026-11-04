"""Independent geometry acceptance checks, not field validation."""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from subsidence import Rectangle, SeamPlane, ValidationError, load_project, save_project
from subsidence.cli import main
from subsidence.config import Project, Spacing
from subsidence.export import export_geometry, geometry_summary
from subsidence.geometry import union_plan_area_m2
from subsidence.mesh import build_source_mesh, build_surface_grid


ROOT = Path(__file__).resolve().parents[1]


def project(**changes):
    base = Project(
        name="Test geometry", evidence="synthetic_geometry",
        field=Rectangle(-10, 10, -10, 10), seam=SeamPlane((0, 0, -100), (0, 0, 1)),
        extraction_rectangles=(Rectangle(0, 4, 0, 2),),
        source_mesh=Spacing(1, 1), surface_grid=Spacing(2, 2),
    )
    return replace(base, **changes)


def independent_union_area(rectangles):
    # Independent oracle: classify all small boxes induced by every input edge.
    xs = sorted({x for r in rectangles for x in (r.xmin_m, r.xmax_m)})
    ys = sorted({y for r in rectangles for y in (r.ymin_m, r.ymax_m)})
    area = 0.0
    for left, right in zip(xs[:-1], xs[1:]):
        for bottom, top in zip(ys[:-1], ys[1:]):
            x, y = (left + right) / 2, (bottom + top) / 2
            if any(r.xmin_m < x < r.xmax_m and r.ymin_m < y < r.ymax_m for r in rectangles):
                area += (right - left) * (top - bottom)
    return area


class GeometryTests(unittest.TestCase):
    def test_normal_scale_sign_and_plane_residual(self):
        a = SeamPlane((4, 7, -100), (-0.1, -0.2, 1))
        b = SeamPlane((4, 7, -100), (1, 2, -10))
        assert_allclose(a.unit_normal, b.unit_normal, atol=1e-15)
        self.assertAlmostEqual(np.linalg.norm(a.unit_normal), 1)
        xy = np.array([[0, 0], [50, -30], [-20, 60]])
        xyz = np.column_stack([xy, a.z_at(xy[:, 0], xy[:, 1])])
        assert_allclose((xyz - a.reference_xyz_m) @ a.unit_normal, 0, atol=2e-14)

    def test_extreme_normal_magnitudes_are_normalized_safely(self):
        for scale in (1e-300, 1e300):
            assert_allclose(SeamPlane((0, 0, -1), (0, scale, 2 * scale)).unit_normal, [0, 1 / np.sqrt(5), 2 / np.sqrt(5)])

    def test_invalid_normal_and_reference(self):
        for normal in ((0, 0, 0), (1, 0, 0), (0, float("nan"), 1), (True, 0, 1), (0, 1)):
            with self.subTest(normal=normal), self.assertRaises(ValidationError):
                SeamPlane((0, 0, -10), normal)
        with self.assertRaises(ValidationError):
            SeamPlane((0, float("inf"), -10), (0, 0, 1))

    def test_rectangle_and_spacing_validation(self):
        for bounds in ((0, 0, 0, 1), (2, 1, 0, 1), (0, 1, 1, 0), (0, float("inf"), 0, 1), (False, 1, 0, 1)):
            with self.subTest(bounds=bounds), self.assertRaises(ValidationError):
                Rectangle(*bounds)
        for step in (0, -1, float("nan"), float("inf"), "10", True):
            with self.subTest(step=step), self.assertRaises(ValidationError):
                Spacing(step, 1)

    def test_surface_crossing_detected_at_corner_even_if_center_is_below(self):
        seam = SeamPlane((0, 0, -1.5), (-0.2, 0, 1))
        self.assertLess(seam.z_at(5, 1), 0)
        with self.assertRaisesRegex(ValidationError, "reaches or crosses"):
            project(seam=seam, extraction_rectangles=(Rectangle(0, 10, 0, 2),))
        with self.assertRaisesRegex(ValidationError, "reference"):
            project(seam=SeamPlane((0, 0, 0), (0, 0, 1)))

    def test_surface_elevation_is_used_for_depth(self):
        p = project(surface_elevation_m=100, seam=SeamPlane((0, 0, 20), (0, 0, 1)))
        assert_allclose(build_source_mesh(p).vertical_depth_m, 80)
        assert_allclose(build_surface_grid(p).xyz_m[:, :, 2], 100)


class ConfigTests(unittest.TestCase):
    def test_round_trip_preserves_reported_normal_and_provenance(self):
        p = load_project(ROOT / "examples/adriyala_geometry.json")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project.json"
            save_project(p, path)
            self.assertEqual(load_project(path).to_dict(), p.to_dict())
        self.assertEqual(p.seam.normal_xyz, (-0.0186, -0.1779, 0.9838))

    def test_schema_units_unknown_keys_and_missing_fields(self):
        changes = [
            {"schema_version": True}, {"schema_version": 2}, {"units": {"length": "ft"}},
            {"name": ""}, {"evidence": "field_validated"}, {"source_mesh": {"dx_m": 2, "dy_m": 2, "dz_m": 1}},
            {"notes": "text"}, {"provenance": []}, {"extraction_rectangles": {}}, {"unused_parameter": 1},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                Project.from_dict(project().to_dict() | change)
        data = project().to_dict()
        del data["field"]
        with self.assertRaises(ValidationError):
            Project.from_dict(data)

    def test_duplicate_and_nonfinite_json_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid.json"
            for content in ('{"name":"a","name":"b"}', '{"name":NaN}', '{"name":Infinity}'):
                path.write_text(content, encoding="utf-8")
                with self.subTest(content=content), self.assertRaises(ValidationError):
                    load_project(path)

    def test_utf8_bom_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project.json"
            path.write_text(json.dumps(project().to_dict()), encoding="utf-8-sig")
            self.assertEqual(load_project(path).name, "Test geometry")


class MeshTests(unittest.TestCase):
    def test_partial_cells_have_exact_areas_and_interior_centers(self):
        p = project(extraction_rectangles=(Rectangle(0, 2.5, 0, 1.2),))
        mesh = build_source_mesh(p)
        self.assertEqual(len(mesh.xyz_m), 6)
        self.assertAlmostEqual(mesh.plan_area_m2.sum(), 3.0)
        assert_allclose(mesh.xyz_m[:, 0], [0.5, 1.5, 2.25, 0.5, 1.5, 2.25])
        assert_allclose(mesh.xyz_m[:, 1], [0.5, 0.5, 0.5, 1.1, 1.1, 1.1])
        assert_allclose(np.average(mesh.xyz_m[:, :2], weights=mesh.plan_area_m2, axis=0), [1.25, 0.6])
        self.assertTrue(np.all(mesh.plan_area_m2 > 0))

    def test_overlapping_rectangles_are_counted_once(self):
        rectangles = (Rectangle(0, 2, 0, 2), Rectangle(1, 3, 1, 3))
        p = project(extraction_rectangles=rectangles, source_mesh=Spacing(1.4, 0.9))
        mesh = build_source_mesh(p)
        self.assertAlmostEqual(mesh.plan_area_m2.sum(), 7)
        for i, a in enumerate(mesh.bounds_xy_m):
            for b in mesh.bounds_xy_m[i + 1:]:
                overlap = max(0, min(a[1], b[1]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[2], b[2]))
                self.assertEqual(overlap, 0)
        reversed_mesh = build_source_mesh(replace(p, extraction_rectangles=rectangles[::-1]))
        assert_array_equal(mesh.bounds_xy_m, reversed_mesh.bounds_xy_m)

    def test_duplicate_touching_nested_and_disconnected_regions(self):
        cases = [
            ((Rectangle(0, 2, 0, 2),) * 2, 4),
            ((Rectangle(0, 1, 0, 1), Rectangle(1, 2, 0, 1)), 2),
            ((Rectangle(0, 3, 0, 3), Rectangle(1, 2, 1, 2)), 9),
            ((Rectangle(0, 0.2, 0, 0.2), Rectangle(0.8, 1, 0.8, 1)), 0.08),
            ((Rectangle(-2.5, -0.2, -1.7, 0.4),), 4.83),
        ]
        for rectangles, area in cases:
            with self.subTest(rectangles=rectangles):
                mesh = build_source_mesh(project(extraction_rectangles=rectangles))
                self.assertAlmostEqual(mesh.plan_area_m2.sum(), area)
                self.assertTrue(all(any(r.xmin_m < x < r.xmax_m and r.ymin_m < y < r.ymax_m for r in rectangles) for x, y, _ in mesh.xyz_m))

    def test_union_matches_independent_oracle_for_random_rectangles(self):
        rng = np.random.default_rng(723)
        for _ in range(30):
            rectangles = []
            for _ in range(5):
                x, y = rng.integers(-8, 8, size=2) / 3
                w, h = rng.integers(1, 8, size=2) / 3
                rectangles.append(Rectangle(x, x + w, y, y + h))
            mesh = build_source_mesh(project(extraction_rectangles=rectangles, source_mesh=Spacing(0.8, 0.6)))
            expected = independent_union_area(rectangles)
            self.assertAlmostEqual(mesh.plan_area_m2.sum(), expected, places=12)
            self.assertAlmostEqual(union_plan_area_m2(rectangles), expected, places=12)

    def test_plan_and_seam_areas_are_distinct_on_inclined_plane(self):
        p = project(seam=SeamPlane((0, 0, -100), (-0.1, -0.1, 1)))
        mesh = build_source_mesh(p)
        assert_allclose(mesh.seam_area_m2, mesh.plan_area_m2 / p.seam.unit_normal[2])
        assert_allclose((mesh.xyz_m - p.seam.reference_xyz_m) @ p.seam.unit_normal, 0, atol=1e-13)
        self.assertTrue(np.all(mesh.vertical_depth_m > 0))

    def test_source_and_surface_meshes_are_independent(self):
        p = project()
        source = build_source_mesh(p)
        surface = build_surface_grid(p)
        changed_surface = replace(p, surface_grid=Spacing(0.7, 1.1), field=Rectangle(-1, 1, -1, 1))
        assert_array_equal(source.xyz_m, build_source_mesh(changed_surface).xyz_m)
        assert_array_equal(source.plan_area_m2, build_source_mesh(changed_surface).plan_area_m2)
        changed_source = replace(p, source_mesh=Spacing(0.3, 0.4))
        assert_array_equal(surface.xyz_m, build_surface_grid(changed_source).xyz_m)

    def test_surface_partial_cells_and_axis_order(self):
        p = project(field=Rectangle(-1, 1.5, -2, -0.8), surface_grid=Spacing(1, 1))
        grid = build_surface_grid(p)
        self.assertEqual(grid.xyz_m.shape, (2, 3, 3))
        assert_allclose(grid.xyz_m[0, :, 0], [-0.5, 0.5, 1.25])
        assert_allclose(grid.xyz_m[:, 0, 1], [-1.5, -0.9])
        assert_allclose(grid.x_edges_m, [-1, 0, 1, 1.5])
        assert_allclose(grid.y_edges_m, [-2, -1, -0.8])

    def test_decimal_spacing_does_not_create_near_zero_boundary_cell(self):
        p = project(extraction_rectangles=(Rectangle(0, 0.9, 0, 0.9),), source_mesh=Spacing(0.3, 0.3))
        self.assertEqual(len(build_source_mesh(p).xyz_m), 9)

    def test_empty_extraction_retains_valid_array_shapes(self):
        p = project(extraction_rectangles=())
        mesh = build_source_mesh(p)
        self.assertEqual(mesh.xyz_m.shape, (0, 3))
        self.assertEqual(mesh.bounds_xy_m.shape, (0, 4))
        self.assertEqual(mesh.plan_area_m2.shape, (0,))
        self.assertEqual(build_surface_grid(p).xyz_m.shape, (10, 10, 3))

    def test_resource_limits_fail_before_large_allocation(self):
        with self.assertRaisesRegex(ValidationError, "limit"):
            build_source_mesh(project(), max_cells=4)
        with self.assertRaisesRegex(ValidationError, "limit"):
            build_surface_grid(project(), max_cells=20)


class ExampleAndExportTests(unittest.TestCase):
    def test_synthetic_example_is_symmetric(self):
        p = load_project(ROOT / "examples/synthetic_flat.json")
        mesh = build_source_mesh(p)
        self.assertEqual(len(mesh.xyz_m), 800)
        self.assertAlmostEqual(mesh.plan_area_m2.sum(), 80000)
        xyz_set = set(map(tuple, mesh.xyz_m))
        self.assertTrue(all((-x, -y, z) in xyz_set for x, y, z in mesh.xyz_m))
        assert_allclose(mesh.xyz_m[:, 2], -400)
        self.assertEqual(build_surface_grid(p).xyz_m.shape, (40, 50, 3))

    def test_adriyala_matches_transcribed_computational_geometry(self):
        p = load_project(ROOT / "examples/adriyala_geometry.json")
        transcription = json.loads((ROOT / "docs/adriyala_reported_inputs.json").read_text(encoding="utf-8"))
        inputs = transcription["computational_inputs"]
        assert_allclose(p.seam.normal_xyz, inputs["seam_normal_as_reported"])
        assert_allclose(p.seam.reference_xyz_m, inputs["seam_reference_xyz_m"])
        self.assertEqual(p.field.width_m, inputs["field_length_m"])
        self.assertEqual(p.field.height_m, inputs["field_breadth_m"])
        grid = build_surface_grid(p)
        mesh = build_source_mesh(p)
        summary = geometry_summary(p, mesh, grid)
        self.assertEqual(grid.xyz_m.shape, (47, 231, 3))
        self.assertEqual(summary["surface_point_count"], 10857)
        self.assertEqual(summary["source_count"], 5775)
        self.assertAlmostEqual(summary["mesh_plan_area_m2"], 577500)
        assert_allclose(summary["extraction_corner_vertical_depth_range_m"], [367.80, 456.68], atol=0.01)
        self.assertAlmostEqual(summary["dip_deg"], 10.305, places=3)
        self.assertLess(summary["max_source_plane_residual_m"], 1e-12)
        self.assertEqual(p.evidence, "reported_geometry")

    def test_export_reopens_without_pickle_and_preserves_config(self):
        p = project()
        mesh, grid = build_source_mesh(p), build_surface_grid(p)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bundle"
            export_geometry(p, mesh, grid, path)
            self.assertEqual({f.name for f in path.iterdir()}, {"project.json", "summary.json", "geometry.npz", "sources.csv", "surface.csv", "preview.svg"})
            self.assertEqual(load_project(path / "project.json").to_dict(), p.to_dict())
            with np.load(path / "geometry.npz", allow_pickle=False) as arrays:
                assert_array_equal(arrays["source_xyz_m"], mesh.xyz_m)
                assert_array_equal(arrays["surface_xyz_m"], grid.xyz_m)
            self.assertEqual(len((path / "sources.csv").read_text().splitlines()), 9)
            self.assertEqual(len((path / "surface.csv").read_text().splitlines()), 101)
            ET.parse(path / "preview.svg")
            with self.assertRaisesRegex(ValidationError, "empty"):
                export_geometry(p, mesh, grid, path)

    def test_empty_export_is_valid(self):
        p = project(extraction_rectangles=(), name="Empty <panel> & geometry")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty"
            summary = export_geometry(p, build_source_mesh(p), build_surface_grid(p), path)
            self.assertIsNone(summary["extraction_corner_vertical_depth_range_m"])
            self.assertEqual(summary["mesh_plan_area_m2"], 0)
            ET.parse(path / "preview.svg")

    def test_cli_validation_mesh_and_error_exit(self):
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["validate", str(ROOT / "examples/synthetic_flat.json")]), 0)
        self.assertIn("Valid geometry", output.getvalue())
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            self.assertEqual(main(["mesh", str(ROOT / "examples/synthetic_flat.json"), "--output", str(Path(tmp) / "cli")]), 0)
        with redirect_stderr(io.StringIO()) as error:
            self.assertEqual(main(["validate", str(ROOT / "examples/missing.json")]), 2)
        self.assertIn("Error:", error.getvalue())


if __name__ == "__main__":
    unittest.main()
