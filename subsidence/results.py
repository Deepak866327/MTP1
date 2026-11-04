"""Flat-solver result bundles, preserving geometry, settings and conventions."""

import csv
import json
from pathlib import Path

import numpy as np

from .config import FlatModel, Project, save_flat_model
from .export import export_geometry
from .geometry import ValidationError
from .mesh import SurfaceGrid
from .plotting import save_displacement_maps
from .solver import DisplacementResult


def export_displacements(project: Project, model: FlatModel, surface: SurfaceGrid, result: DisplacementResult, output: str | Path) -> dict:
    if result.xyz_m.shape != surface.xyz_m.shape or not np.array_equal(result.xyz_m, surface.xyz_m):
        raise ValidationError("Grid export requires results at exactly the supplied surface-grid coordinates.")
    if result.metadata["settings"] != model.to_dict():
        raise ValidationError("Result settings differ from the requested export model.")
    if result.metadata["project"] != project.to_dict():
        raise ValidationError("Result project differs from the requested export geometry.")
    target = Path(output)
    # Reuse the Phase 1 artifact contract and its empty-directory protection.
    export_geometry(project, result.sources, surface, target)
    save_flat_model(model, target / "model.json")
    np.savez_compressed(target / "displacement.npz", xyz_m=result.xyz_m, displacement_m=result.displacement_m, ux_m=result.ux_m, uy_m=result.uy_m, uz_m=result.uz_m, settlement_m=-result.uz_m)
    with (target / "displacement.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["row_y", "col_x", "x_m", "y_m", "z_m", "ux_m", "uy_m", "uz_m", "settlement_m"])
        for row_y in range(surface.xyz_m.shape[0]):
            for col_x in range(surface.xyz_m.shape[1]):
                writer.writerow([row_y, col_x, *result.xyz_m[row_y, col_x], *result.displacement_m[row_y, col_x], -result.uz_m[row_y, col_x]])
    statistics = {}
    for index, label in enumerate(("ux_m", "uy_m", "uz_m")):
        values = result.displacement_m[..., index]
        statistics[label] = {"min": float(values.min()), "max": float(values.max()), "mean": float(values.mean())}
    minimum = np.unravel_index(np.argmin(result.uz_m), result.uz_m.shape)
    summary = {
        **result.metadata,
        "name": project.name,
        "status": "flat_seam_displacement_no_field_validation",
        "statistics": statistics,
        "peak_sampled_settlement_m": float(-result.uz_m[minimum]),
        "peak_sampled_settlement_xyz_m": result.xyz_m[minimum].tolist(),
        "peak_note": "Maximum among the requested grid samples; not a continuous peak search.",
        "provenance": project.provenance,
        "notes": list(project.notes),
    }
    (target / "result_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    save_displacement_maps(project, surface, result, target)
    return summary
