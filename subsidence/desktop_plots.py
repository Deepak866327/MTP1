"""Scientific figures shared by the desktop UI and headless verification."""

import numpy as np
from matplotlib.colors import TwoSlopeNorm
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle as RectanglePatch

from .workspace import FIELDS


def field_figure(run, name, colormap):
    figure = Figure(figsize=(8, 6), layout="constrained")
    axis = figure.subplots()
    values = run.values(name)
    norm = None
    if name in ("Ex", "Ey", "Ux", "Uy"):
        limit = max(float(np.abs(values).max()), 1e-12)
        norm = TwoSlopeNorm(vmin=-limit, vcenter=0, vmax=limit)
        if name in ("Ex", "Ey") and colormap not in ("coolwarm", "RdBu_r"):
            colormap = "RdBu_r"
    artist = axis.pcolormesh(run.surface.x_edges_m, run.surface.y_edges_m, values, shading="flat", cmap=colormap, norm=norm, rasterized=True)
    figure.colorbar(artist, ax=axis, label=f"{name} ({FIELDS[name]})")
    for rect in run.document.project.extraction_rectangles:
        axis.add_patch(RectanglePatch((rect.xmin_m, rect.ymin_m), rect.xmax_m - rect.xmin_m, rect.ymax_m - rect.ymin_m, fill=False, linewidth=1, edgecolor="black"))
    for line in run.document.profiles:
        axis.plot([line.start_xy_m[0], line.end_xy_m[0]], [line.start_xy_m[1], line.end_xy_m[1]], "k--", linewidth=0.8)
    axis.set(xlabel="Global x (m)", ylabel="Global y (m)", title=f"{run.document.project.name}\n{name} | {run.document.project.evidence}")
    axis.set_aspect("equal")
    return figure


def profile_figure(profile, name):
    figure = Figure(figsize=(8, 5), layout="constrained")
    axis = figure.subplots()
    values = {"Ux": profile.displacement_m[:, 0], "Uy": profile.displacement_m[:, 1], "Uz": profile.displacement_m[:, 2], "Settlement": -profile.displacement_m[:, 2], "Ex": 1000 * profile.ex, "Ey": 1000 * profile.ey}[name]
    axis.plot(profile.distance_m, values, linewidth=2)
    if name in ("Ex", "Ey") and profile.boundary_influenced.any():
        mask = profile.boundary_influenced
        axis.scatter(profile.distance_m[mask], values[mask], s=15, color="darkorange", label="Uses a one-sided boundary stencil")
        axis.legend()
    axis.axhline(0, color="gray", linewidth=0.6)
    axis.grid(True, alpha=0.2)
    axis.set(xlabel="Distance along profile (m)", ylabel=f"{name} ({FIELDS[name]})", title=f"{profile.line.name} | global component, interpolated from saved grid")
    return figure


def station_figure(run, line_id):
    figure = Figure(figsize=(8, 5.5), layout="constrained")
    axis, residual_axis = figure.subplots(2, 1, sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    data = run.document.observations
    indices = [i for i, s in enumerate(data.stations) if s.line_id == line_id]
    if data.stations[indices[0]].distance_m is not None:
        indices.sort(key=lambda i: data.stations[i].distance_m)
        x = np.array([data.stations[i].distance_m for i in indices])
        label = "Supplied monitoring-line distance (m)"
    else:
        x = np.arange(len(indices))
        label = "Station (original CSV order)"
        residual_axis.set_xticks(x, [data.stations[i].station_id for i in indices], rotation=45, ha="right")
    observed = np.array([data.stations[i].uz_observed_m for i in indices])
    predicted = run.evaluation.prediction.uz_m[indices]
    axis.plot(x, observed, "o-", label="Observed (canonical Uz)")
    axis.plot(x, predicted, "s-", label="Frozen model at exact stations")
    residual_axis.plot(x, predicted - observed, "o-", markersize=3)
    residual_axis.axhline(0, color="black", linewidth=0.8)
    axis.set(ylabel="Uz (m); negative downward", title=f"{line_id} ({data.metadata.line_roles[line_id]}) | {data.metadata.evidence}")
    residual_axis.set(xlabel=label, ylabel="Residual (m)")
    axis.legend(fontsize=9)
    for item in (axis, residual_axis):
        item.grid(True, alpha=0.2)
    return figure
