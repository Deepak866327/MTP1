"""Portable static SVG geometry preview, with no graphical runtime dependency."""

from html import escape
import math

import numpy as np

from .config import Project
from .mesh import SourceMesh, SurfaceGrid


def _sample(points: np.ndarray, limit: int = 1200) -> np.ndarray:
    if len(points) <= limit:
        return points
    return points[np.linspace(0, len(points) - 1, limit, dtype=int)]


def geometry_svg(project: Project, sources: SourceMesh, surface: SurfaceGrid) -> str:
    elements = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="880" viewBox="0 0 1200 880" role="img">',
        f'<title>{escape(project.name)} — geometry preview</title>',
        '<desc>Extraction plan, sampled source and surface points, and projected seam section. Geometry only.</desc>',
        '<style>text{font-family:Arial,sans-serif;fill:#18324b} .small{font-size:13px} .tick{font-size:12px;fill:#536c82}</style>',
        '<rect width="1200" height="880" fill="#f4f7fa"/>',
        f'<text x="40" y="42" font-size="24" font-weight="bold">{escape(project.name)}</text>',
        f'<text x="40" y="69" class="small">{escape(project.evidence)} | Phase 1 geometry | z positive upward | lengths in metres</text>',
        '<rect x="25" y="95" width="740" height="625" rx="12" fill="white" stroke="#d9e2eb"/>',
        '<rect x="785" y="95" width="390" height="625" rx="12" fill="white" stroke="#d9e2eb"/>',
        '<text x="45" y="126" font-size="18" font-weight="bold">Plan view</text>',
        '<text x="805" y="126" font-size="18" font-weight="bold">Seam section</text>',
    ]
    rectangles = (project.field, *project.extraction_rectangles)
    xmin, xmax = min(r.xmin_m for r in rectangles), max(r.xmax_m for r in rectangles)
    ymin, ymax = min(r.ymin_m for r in rectangles), max(r.ymax_m for r in rectangles)
    # Equal x/y scales preserve plan aspect ratio, including long narrow panels.
    scale = min(610 / (xmax - xmin), 450 / (ymax - ymin))
    left = 100 + (610 - scale * (xmax - xmin)) / 2
    top = 180 + (450 - scale * (ymax - ymin)) / 2

    def px(x):
        return left + (x - xmin) * scale

    def py(y):
        return top + (ymax - y) * scale

    for index, rectangle in enumerate(rectangles):
        color = "#468ab9" if index == 0 else "#d58226"
        fill = "#edf5fb" if index == 0 else "#fff1d9"
        elements.append(
            f'<rect x="{px(rectangle.xmin_m):.3f}" y="{py(rectangle.ymax_m):.3f}" '
            f'width="{rectangle.width_m * scale:.3f}" height="{rectangle.height_m * scale:.3f}" '
            f'fill="{fill}" fill-opacity="0.65" stroke="{color}" stroke-width="1.5"/>'
        )
    for points, color, radius in (
        (surface.xyz_m.reshape(-1, 3), "#85a7bd", 1.1),
        (sources.xyz_m, "#a9560d", 1.5),
    ):
        for x, y, _ in _sample(points):
            elements.append(f'<circle cx="{px(x):.3f}" cy="{py(y):.3f}" r="{radius}" fill="{color}"/>')
    for fraction in np.linspace(0, 1, 5):
        x, y = xmin + fraction * (xmax - xmin), ymin + fraction * (ymax - ymin)
        elements.append(f'<text x="{px(x):.2f}" y="{py(ymin) + 23:.2f}" text-anchor="middle" class="tick">{x:.1f}</text>')
        elements.append(f'<text x="{px(xmin) - 10:.2f}" y="{py(y) + 4:.2f}" text-anchor="end" class="tick">{y:.1f}</text>')
    elements.extend([
        '<text x="395" y="675" text-anchor="middle" class="small">Global x (m), right; global y (m), up</text>',
        '<text x="45" y="699" class="small">Blue: observation field / points. Orange: extraction / source points (sampled).</text>',
    ])

    nx, ny, _ = project.seam.unit_normal
    horizontal = math.hypot(nx, ny)
    direction = np.array([nx, ny]) / horizontal if horizontal > 1e-12 else np.array([1.0, 0.0])
    corners = np.concatenate([r.corners_xy_m for r in project.extraction_rectangles]) if project.extraction_rectangles else project.field.corners_xy_m
    reference = np.array(project.seam.reference_xyz_m)
    distance = (corners - reference[:2]) @ direction
    low, high = float(distance.min()), float(distance.max())
    margin = max((high - low) * 0.1, 1.0)
    low, high = low - margin, high + margin
    section_xy = reference[:2] + np.array([low, high])[:, None] * direction
    seam_z = project.seam.z_at(section_xy[:, 0], section_xy[:, 1])
    zlow = min(float(seam_z.min()), project.surface_elevation_m) - 30
    zhigh = max(float(seam_z.max()), project.surface_elevation_m) + 30

    def sx(t):
        return 850 + (t - low) / (high - low) * 290

    def sz(z):
        return 185 + (zhigh - z) / (zhigh - zlow) * 440

    elements.append(f'<line x1="850" y1="{sz(project.surface_elevation_m):.2f}" x2="1140" y2="{sz(project.surface_elevation_m):.2f}" stroke="#468ab9" stroke-width="2"/>')
    elements.append(f'<line x1="850" y1="{sz(seam_z[0]):.2f}" x2="1140" y2="{sz(seam_z[1]):.2f}" stroke="#d58226" stroke-width="2"/>')
    for x, y, z in _sample(sources.xyz_m, 200):
        t = (np.array([x, y]) - reference[:2]) @ direction
        elements.append(f'<circle cx="{sx(t):.2f}" cy="{sz(z):.2f}" r="2" fill="#a9560d"/>')
    for z in np.linspace(zlow, zhigh, 5):
        elements.append(f'<text x="842" y="{sz(z) + 4:.2f}" text-anchor="end" class="tick">{z:.0f}</text>')
    for t in np.linspace(low, high, 3):
        elements.append(f'<text x="{sx(t):.2f}" y="650" text-anchor="middle" class="tick">{t:.1f}</text>')
    elements.extend([
        '<text x="805" y="153" class="small">Global z (m); surface shown in blue</text>',
        '<text x="805" y="675" class="small">Distance along dip from reference (m)</text>' if horizontal > 1e-12 else '<text x="805" y="675" class="small">Distance along x from reference (m)</text>',
        '<text x="805" y="699" class="small">Vertical and horizontal scales differ.</text>',
        f'<text x="40" y="759" font-size="16">{len(sources.xyz_m):,} source cells | {surface.xyz_m.shape[0] * surface.xyz_m.shape[1]:,} surface points | dip {project.seam.dip_deg:.4f}°</text>',
        f'<text x="40" y="786" class="small">Source spacing: {project.source_mesh.dx_m:g} × {project.source_mesh.dy_m:g} m. Surface spacing: {project.surface_grid.dx_m:g} × {project.surface_grid.dy_m:g} m.</text>',
        '<text x="40" y="815" class="small">Geometry reconstruction only. No displacement, strain, calibration, or field accuracy is calculated.</text>',
        '</svg>',
    ])
    return "\n".join(elements) + "\n"
