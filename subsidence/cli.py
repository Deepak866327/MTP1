"""Geometry, flat-seam prediction and repeatable numerical verification."""

import argparse
import json
import sys

from .config import load_flat_model, load_project
from .export import export_geometry
from .mesh import build_source_mesh, build_surface_grid
from .solver import solve_flat


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Subsidence rebuild — geometry and flat-seam displacement.")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Validate a version-1 project and physical geometry.")
    validate.add_argument("project", help="Path to project JSON.")
    mesh = commands.add_parser("mesh", help="Generate independent meshes, CSV/NPZ arrays and SVG preview.")
    mesh.add_argument("project", help="Path to project JSON.")
    mesh.add_argument("--output", required=True, help="New or empty artifact directory.")
    solve = commands.add_parser("solve-flat", help="Calculate Ux, Uy, Uz for a horizontal seam.")
    solve.add_argument("project", help="Geometry project JSON.")
    solve.add_argument("--model", required=True, help="Separate flat-model settings JSON.")
    solve.add_argument("--output", required=True, help="New or empty result directory.")
    solve.add_argument("--observation-chunk-size", type=int, default=128)
    solve.add_argument("--source-chunk-size", type=int, default=2048)
    verify = commands.add_parser("verify-flat", help="Run synthetic acceptance checks and analytical convergence study.")
    verify.add_argument("--output", required=True, help="New or empty verification directory.")
    args = parser.parse_args(argv)
    try:
        if args.command == "verify-flat":
            from .verification import export_flat_verification, run_flat_verification
            report = run_flat_verification()
            export_flat_verification(report, args.output)
            print(json.dumps({"passed": report["passed"], "output": args.output, "check_count": len(report["checks"]), "finest_mesh_max_error_m": report["convergence"][-1]["max_component_error_m"]}, indent=2))
            return 0 if report["passed"] else 1
        project = load_project(args.project)
        if args.command == "validate":
            print(f"Valid geometry: {project.name} ({project.evidence}); dip {project.seam.dip_deg:.4f} degrees.")
        elif args.command == "mesh":
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
        else:
            from .results import export_displacements
            model = load_flat_model(args.model)
            surface = build_surface_grid(project)
            result = solve_flat(project, model, surface.xyz_m, observation_chunk_size=args.observation_chunk_size, source_chunk_size=args.source_chunk_size)
            summary = export_displacements(project, model, surface, result, args.output)
            print(json.dumps({"output": args.output, "source_count": summary["source_count"], "evaluation_point_count": summary["evaluation_point_count"], "peak_sampled_settlement_m": summary["peak_sampled_settlement_m"], "status": summary["status"]}, indent=2))
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 0
