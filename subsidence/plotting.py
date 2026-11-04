"""Standalone scientific plots; no GUI backend or interactive app is required."""

from pathlib import Path

from matplotlib.figure import Figure
from matplotlib.patches import Rectangle as PlotRectangle
import numpy as np

from .config import Project
from .deformation import StrainResult
from .mesh import SurfaceGrid
from .profiles import ProfileResult
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
    label = "Seam-frame Gaussian (v1 reconstruction)" if result.metadata["model"] == "inclined_seam_frame_gaussian_v1" else "Flat Gaussian model"
    figure.suptitle(f"{project.name}\n{label} | {project.evidence} | Uz negative downward | dashed outlines: extraction", fontsize=12)
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


def save_strain_maps(project: Project, surface: SurfaceGrid, strain: StrainResult, output: Path) -> None:
    figure = Figure(figsize=(11, 5), layout="constrained")
    axes = figure.subplots(1, 2)
    limit = max(float(np.max(np.abs(strain.ex_mm_per_m))), float(np.max(np.abs(strain.ey_mm_per_m))), 1e-12)
    for axis, label, values in zip(axes, ("Ex = dUx/dx", "Ey = dUy/dy"), (strain.ex_mm_per_m, strain.ey_mm_per_m)):
        artist = axis.pcolormesh(surface.x_edges_m, surface.y_edges_m, values, cmap="RdBu_r", vmin=-limit, vmax=limit, shading="flat", rasterized=True)
        for r in project.extraction_rectangles:
            axis.add_patch(PlotRectangle((r.xmin_m, r.ymin_m), r.width_m, r.height_m, fill=False, edgecolor="#333333", linestyle="--", linewidth=0.8))
        axis.set(xlabel="Global x (m)", ylabel="Global y (m)", title=label, aspect="equal", xlim=(surface.x_edges_m[0], surface.x_edges_m[-1]), ylim=(surface.y_edges_m[0], surface.y_edges_m[-1]))
        figure.colorbar(artist, ax=axis, shrink=0.8, label="Normal strain (mm/m)")
    figure.suptitle(f"{project.name}\nPositive: tensile; negative: compressive | one-sided derivatives at outer centers", fontsize=12)
    figure.savefig(output / "strain_maps.png", dpi=160)
    figure.savefig(output / "strain_maps.svg")


def save_profile_plot(profile: ProfileResult, output: Path, stem: str) -> None:
    figure = Figure(figsize=(9, 7), layout="constrained")
    displacement_axis, strain_axis = figure.subplots(2, 1, sharex=True)
    for index, label in enumerate(("Ux", "Uy", "Uz")):
        displacement_axis.plot(profile.distance_m, profile.displacement_m[:, index], label=label)
    displacement_axis.set(ylabel="Displacement (m)")
    displacement_axis.legend()
    for label, values in (("Ex", profile.ex * 1000), ("Ey", profile.ey * 1000)):
        line, = strain_axis.plot(profile.distance_m, values, label=f"Global {label}")
        marked = profile.boundary_influenced
        if marked.any():
            strain_axis.scatter(profile.distance_m[marked], values[marked], s=14, facecolors="none", edgecolors=line.get_color())
    strain_axis.set(xlabel="Distance from profile start (m)", ylabel="Normal strain (mm/m)")
    strain_axis.legend()
    for axis in (displacement_axis, strain_axis):
        axis.axhline(0, color="#555555", linewidth=0.5)
        axis.grid(True, alpha=0.25)
    figure.suptitle(f"{profile.line.name}\n{profile.line.start_xy_m} to {profile.line.end_xy_m} m\nEx/Ey are global components; hollow markers indicate boundary-influenced samples", fontsize=11)
    figure.savefig(output / f"{stem}.png", dpi=160)
    figure.savefig(output / f"{stem}.svg")
