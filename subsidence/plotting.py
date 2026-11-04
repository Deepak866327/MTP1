"""Standalone scientific plots; no GUI backend or interactive app is required."""

from pathlib import Path

from matplotlib.figure import Figure
from matplotlib.patches import Rectangle as PlotRectangle
import numpy as np

from .config import Project
from .mesh import SurfaceGrid
from .solver import DisplacementResult


def save_displacement_maps(project: Project, surface: SurfaceGrid, result: DisplacementResult, output: Path) -> None:
    figure = Figure(figsize=(14, 5), layout="constrained")
    axes = figure.subplots(1, 3)
    for index, (axis, label) in enumerate(zip(axes, ("Ux", "Uy", "Uz"))):
        values = result.displacement_m[..., index]
        if index < 2:
            limit = max(float(np.max(np.abs(values))), 1e-12)
            palette, limits = "RdBu_r", {"vmin": -limit, "vmax": limit}
        else:
            palette = "viridis"
            limits = {"vmin": min(float(values.min()), -1e-12), "vmax": 0}
        artist = axis.pcolormesh(surface.x_edges_m, surface.y_edges_m, values, cmap=palette, shading="flat", rasterized=True, **limits)
        for rectangle in project.extraction_rectangles:
            axis.add_patch(PlotRectangle((rectangle.xmin_m, rectangle.ymin_m), rectangle.width_m, rectangle.height_m, fill=False, edgecolor="#333333", linewidth=0.8, linestyle="--"))
        axis.set(xlabel="Global x (m)", ylabel="Global y (m)", title=f"{label} (m)", xlim=(surface.x_edges_m[0], surface.x_edges_m[-1]), ylim=(surface.y_edges_m[0], surface.y_edges_m[-1]), aspect="equal")
        figure.colorbar(artist, ax=axis, shrink=0.75, label="Displacement (m)")
    figure.suptitle(f"{project.name}\nFlat Gaussian model | {project.evidence} | Uz negative downward | dashed outlines: extraction", fontsize=12)
    figure.savefig(output / "displacement_maps.png", dpi=160)
    figure.savefig(output / "displacement_maps.svg")


def save_convergence_plot(rows: list[dict], output: Path) -> None:
    figure = Figure(figsize=(7, 4.8), layout="constrained")
    axis = figure.subplots()
    spacing = np.array([row["source_spacing_m"] for row in rows])
    error = np.array([row["max_component_error_m"] for row in rows])
    axis.loglog(spacing, error, "o-", label="Maximum component error vs analytical integral")
    axis.loglog(spacing, error[0] * (spacing / spacing[0]) ** 2, "--", label="Second-order guide")
    axis.set(xlabel="Source spacing (m)", ylabel="Maximum absolute displacement error (m)", title="Synthetic flat-panel midpoint convergence")
    axis.grid(True, which="both", alpha=0.3)
    axis.legend(fontsize=9)
    figure.savefig(output / "convergence.png", dpi=160)
    figure.savefig(output / "convergence.svg")
