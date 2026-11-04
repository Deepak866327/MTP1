"""Reviewable Phase 1 artifacts with explicit shapes, units and evidence labels."""

import csv
import json
from pathlib import Path

import numpy as np

from .config import Project, save_project
from .geometry import ValidationError, union_plan_area_m2
from .mesh import SourceMesh, SurfaceGrid
from .preview import geometry_svg


def geometry_summary(project: Project, sources: SourceMesh, surface: SurfaceGrid) -> dict:
    corners = [r.corners_xy_m for r in project.extraction_rectangles]
    if corners:
        xy = np.concatenate(corners)
        depths = project.surface_elevation_m - project.seam.z_at(xy[:, 0], xy[:, 1])
        depth_range = [float(depths.min()), float(depths.max())]
    else:
        depth_range = None
    residual = (sources.xyz_m - project.seam.reference_xyz_m) @ np.array(project.seam.unit_normal)
    exact_area = union_plan_area_m2(project.extraction_rectangles)
    mesh_area = float(sources.plan_area_m2.sum())
    return {
        "phase": 1,
        "name": project.name,
        "evidence": project.evidence,
        "status": "geometry_only_no_prediction_or_field_validation",
        "coordinate_convention": "Global Cartesian; metres; z positive upward; horizontal surface.",
        "unit_normal_xyz": list(project.seam.unit_normal),
        "input_normal_xyz": list(project.seam.normal_xyz),
        "dip_deg": project.seam.dip_deg,
        "source_count": len(sources.xyz_m),
        "surface_point_count": int(np.prod(surface.xyz_m.shape[:2])),
        "surface_shape_yx": list(surface.xyz_m.shape[:2]),
        "source_nominal_spacing_m": [project.source_mesh.dx_m, project.source_mesh.dy_m],
        "surface_nominal_spacing_m": [project.surface_grid.dx_m, project.surface_grid.dy_m],
        "extraction_union_plan_area_m2": exact_area,
        "mesh_plan_area_m2": mesh_area,
        "mesh_seam_area_m2": float(sources.seam_area_m2.sum()),
        "plan_area_error_m2": mesh_area - exact_area,
        "extraction_corner_vertical_depth_range_m": depth_range,
        "source_center_vertical_depth_range_m": [float(sources.vertical_depth_m.min()), float(sources.vertical_depth_m.max())] if len(sources.xyz_m) else None,
        "max_source_plane_residual_m": float(np.max(np.abs(residual))) if len(residual) else 0.0,
        "array_conventions": {
            "source_xyz_m": "(n_sources, 3); columns x, y, z",
            "source_bounds_xy_m": "(n_sources, 4); columns xmin, xmax, ymin, ymax",
            "surface_xyz_m": "(ny, nx, 3); [row_y, col_x]; C flattening varies x fastest",
            "area_policy": "Both plan and seam areas exported; no solver area convention selected.",
            "partial_cells": "Exact rectangular fragments at union and mesh boundaries; midpoint per fragment.",
        },
        "warnings": ["Geometry exceeds the report's approximately 12-degree prediction scope."] if project.seam.dip_deg > 12 else [],
        "provenance": project.provenance,
        "notes": list(project.notes),
    }


def export_geometry(project: Project, sources: SourceMesh, surface: SurfaceGrid, output: str | Path) -> dict:
    target = Path(output)
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValidationError(f"Output directory must be empty: {target}. Choose a new output path.")
    target.mkdir(parents=True, exist_ok=True)
    summary = geometry_summary(project, sources, surface)
    save_project(project, target / "project.json")
    (target / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    np.savez_compressed(
        target / "geometry.npz",
        source_xyz_m=sources.xyz_m, source_bounds_xy_m=sources.bounds_xy_m,
        source_plan_area_m2=sources.plan_area_m2, source_seam_area_m2=sources.seam_area_m2,
        source_vertical_depth_m=sources.vertical_depth_m,
        surface_xyz_m=surface.xyz_m, surface_x_edges_m=surface.x_edges_m,
        surface_y_edges_m=surface.y_edges_m,
    )
    with (target / "sources.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source_id", "x_m", "y_m", "z_m", "plan_area_m2", "seam_area_m2", "vertical_depth_m", "xmin_m", "xmax_m", "ymin_m", "ymax_m"])
        for index, xyz in enumerate(sources.xyz_m):
            writer.writerow([index, *xyz, sources.plan_area_m2[index], sources.seam_area_m2[index], sources.vertical_depth_m[index], *sources.bounds_xy_m[index]])
    with (target / "surface.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["row_y", "col_x", "x_m", "y_m", "z_m"])
        for row_y in range(surface.xyz_m.shape[0]):
            for col_x in range(surface.xyz_m.shape[1]):
                writer.writerow([row_y, col_x, *surface.xyz_m[row_y, col_x]])
    (target / "preview.svg").write_text(geometry_svg(project, sources, surface), encoding="utf-8")
    return summary
