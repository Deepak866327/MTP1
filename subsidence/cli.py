"""Command-line entry points for validating and exporting geometry."""

import argparse
import json
import sys

from .config import load_project
from .export import export_geometry
from .mesh import build_source_mesh, build_surface_grid


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Subsidence rebuild ? Phase 1 geometry, no prediction solver.")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Validate a version-1 project and physical geometry.")
    validate.add_argument("project", help="Path to project JSON.")
    mesh = commands.add_parser("mesh", help="Generate independent meshes, CSV/NPZ arrays and SVG preview.")
    mesh.add_argument("project", help="Path to project JSON.")
    mesh.add_argument("--output", required=True, help="New or empty artifact directory.")
    args = parser.parse_args(argv)
    try:
        project = load_project(args.project)
        if args.command == "validate":
            print(f"Valid geometry: {project.name} ({project.evidence}); dip {project.seam.dip_deg:.4f} degrees.")
        else:
            sources = build_source_mesh(project)
            surface = build_surface_grid(project)
            summary = export_geometry(project, sources, surface, args.output)
            print(json.dumps({
                "output": str(args.output),
                "source_count": summary["source_count"],
                "surface_shape_yx": summary["surface_shape_yx"],
                "extraction_union_plan_area_m2": summary["extraction_union_plan_area_m2"],
                "corner_vertical_depth_range_m": summary["extraction_corner_vertical_depth_range_m"],
                "status": summary["status"],
            }, indent=2))
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 0
