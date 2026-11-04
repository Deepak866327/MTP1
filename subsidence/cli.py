"""Geometry, flat-seam prediction and repeatable numerical verification."""

import argparse
import json
import sys

from .config import load_flat_model, load_model, load_project
from .export import export_geometry
from .mesh import build_source_mesh, build_surface_grid
from .solver import solve_flat


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Subsidence rebuild — flat/inclined displacement, strain and profiles.")
    commands = parser.add_subparsers(dest="command", required=True)
    gui = commands.add_parser("gui", help="Open the local desktop workbench for prediction, profiles and calibration.")
    gui.add_argument("--project", help="Optional saved desktop project JSON to open.")
    desktop_verify = commands.add_parser("verify-desktop", help="Create synthetic desktop run bundles and verify exact reopening.")
    desktop_verify.add_argument("--output", required=True, help="New or empty verification directory.")
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
    deform = commands.add_parser("deform-flat", help="Calculate displacement, Ex/Ey and optional line profiles.")
    deform.add_argument("project", help="Geometry project JSON.")
    deform.add_argument("--model", required=True, help="Flat-model settings JSON.")
    deform.add_argument("--profiles", help="Optional line-profile definitions JSON.")
    deform.add_argument("--output", required=True, help="New or empty result directory.")
    sample = commands.add_parser("sample-profiles", help="Sample saved displacements and derived Ex/Ey without rerunning the solver.")
    sample.add_argument("run", help="Existing solve-flat or deform-flat output directory.")
    sample.add_argument("--profiles", required=True, help="Line-profile definitions JSON.")
    sample.add_argument("--output", required=True, help="New or empty profile directory.")
    verify_deformation = commands.add_parser("verify-deformation", help="Verify strain derivatives and line interpolation.")
    verify_deformation.add_argument("--output", required=True, help="New or empty verification directory.")
    for name, description in (("solve-inclined", "Calculate gently inclined seam Ux/Uy/Uz using explicit v1 conventions."), ("deform-inclined", "Calculate gently inclined displacement, Ex/Ey and optional profiles.")):
        command = commands.add_parser(name, help=description)
        command.add_argument("project", help="Geometry project JSON (dip 0–12 degrees).")
        command.add_argument("--model", required=True, help="Explicit inclined-model settings JSON.")
        command.add_argument("--output", required=True, help="New or empty result directory.")
        command.add_argument("--observation-chunk-size", type=int, default=128)
        command.add_argument("--source-chunk-size", type=int, default=2048)
        if name == "deform-inclined":
            command.add_argument("--profiles", help="Optional line-profile definitions JSON.")
    verify_inclined = commands.add_parser("verify-inclined", help="Verify transformations, zero dip and inclined numerical convergence.")
    verify_inclined.add_argument("--output", required=True, help="New or empty verification directory.")
    evaluate = commands.add_parser("evaluate-stations", help="Compare frozen-model predictions with supplied station measurements.")
    evaluate.add_argument("project", help="Geometry project JSON.")
    evaluate.add_argument("--model", required=True, help="Flat or inclined settings JSON.")
    evaluate.add_argument("--observations", required=True, help="Station coordinates/observed Uz CSV.")
    evaluate.add_argument("--metadata", required=True, help="Measurement provenance, datum/sign/stage and line roles JSON.")
    evaluate.add_argument("--output", required=True, help="New or empty comparison directory.")
    audit = commands.add_parser("audit-report-profiles", help="Audit approximate digitized published curves; no station coordinates inferred.")
    audit.add_argument("traces", help="Pixel traces/calibration/provenance JSON.")
    audit.add_argument("--output", required=True, help="New or empty audit directory.")
    verify_baseline = commands.add_parser("verify-baseline", help="Verify station ingestion, sign conversion and known residual metrics on synthetic data.")
    verify_baseline.add_argument("--output", required=True, help="New or empty verification directory.")
    calibrate = commands.add_parser("calibrate-stations", help="Fit amplitude/beta on fit-role stations, then evaluate frozen settings on test stations.")
    calibrate.add_argument("project", help="Geometry project JSON.")
    calibrate.add_argument("--model", required=True, help="Manual flat/inclined comparison settings JSON.")
    calibrate.add_argument("--observations", required=True, help="Station coordinates/observed Uz CSV.")
    calibrate.add_argument("--metadata", required=True, help="Measurement provenance and predefined fit/test roles JSON.")
    calibrate.add_argument("--settings", required=True, help="Explicit bounds, justification, starts and optimizer settings JSON.")
    calibrate.add_argument("--output", required=True, help="New or empty calibration directory.")
    verify_calibration = commands.add_parser("verify-calibration", help="Recover known synthetic parameters using independent references and held-out stations.")
    verify_calibration.add_argument("--output", required=True, help="New or empty verification directory.")
    args = parser.parse_args(argv)
    try:
        if args.command == "gui":
            from .desktop import launch
            launch(args.project)
            return 0
        if args.command == "verify-desktop":
            from .phase7_verification import export_desktop_verification
            report = export_desktop_verification(args.output)
            print(json.dumps({"output": args.output, "passed": report["passed"], "check_count": len(report["checks"]), "evidence": report["evidence"]}, indent=2))
            return 0 if report["passed"] else 1
        if args.command == "verify-calibration":
            from .phase6_verification import export_calibration_verification
            report = export_calibration_verification(args.output)
            print(json.dumps({"output": args.output, "passed": report["passed"], "check_count": len(report["checks"]), "evidence": report["evidence"]}, indent=2))
            return 0 if report["passed"] else 1
        if args.command == "calibrate-stations":
            from .calibration import CalibrationFailure, calibrate_stations, load_calibration_settings
            from .observations import load_observations
            from .phase6_results import export_calibration, export_calibration_failure
            project, model = load_project(args.project), load_model(args.model)
            dataset = load_observations(args.observations, args.metadata)
            settings = load_calibration_settings(args.settings)
            try:
                result = calibrate_stations(project, model, dataset, settings)
            except CalibrationFailure as failure:
                summary = export_calibration_failure(project, model, dataset, settings, failure, args.output)
                print(json.dumps({"output": args.output, **summary}, indent=2))
                return 1
            summary = export_calibration(result, args.output)
            print(json.dumps({"output": args.output, "status": summary["status"], "fitted_model": summary["fitted_model"], "role_metrics": summary["fitted_role_metrics"], "warnings": summary["diagnostics"]["warnings"]}, indent=2))
            return 0
        if args.command == "verify-baseline":
            from .phase5_verification import export_baseline_verification
            report = export_baseline_verification(args.output)
            print(json.dumps({"output": args.output, "passed": report["passed"], "check_count": len(report["checks"]), "evidence": report["evidence"]}, indent=2))
            return 0 if report["passed"] else 1
        if args.command == "audit-report-profiles":
            from .digitization import load_digitized_report
            from .phase5_results import export_digitized_report
            report = load_digitized_report(args.traces)
            summary = export_digitized_report(report, args.output)
            print(json.dumps({"output": args.output, "status": summary["status"], "lines": [{"line_id": l["line_id"], "digitized_curve_rmse_m": l["rmse_m"], "source_reported_rmse_m": l["reported_rmse_m"]} for l in summary["lines"]]}, indent=2))
            return 0
        if args.command == "evaluate-stations":
            from .evaluation import evaluate_stations
            from .observations import load_observations
            from .phase5_results import export_baseline
            project, model = load_project(args.project), load_model(args.model)
            dataset = load_observations(args.observations, args.metadata)
            result = evaluate_stations(project, model, dataset)
            summary = export_baseline(project, model, result, args.output)
            print(json.dumps({"output": args.output, "status": summary["status"], "line_metrics": summary["line_metrics"]}, indent=2))
            return 0
        if args.command == "verify-inclined":
            from .phase4_verification import export_inclined_verification, run_inclined_verification
            report = run_inclined_verification()
            export_inclined_verification(report, args.output)
            print(json.dumps({"passed": report["passed"], "output": args.output, "check_count": len(report["checks"])}, indent=2))
            return 0 if report["passed"] else 1
        if args.command == "verify-deformation":
            from .phase3_verification import export_deformation_verification, run_deformation_verification
            report = run_deformation_verification()
            export_deformation_verification(report, args.output)
            print(json.dumps({"passed": report["passed"], "output": args.output, "check_count": len(report["checks"])}, indent=2))
            return 0 if report["passed"] else 1
        if args.command == "sample-profiles":
            from .deformation import horizontal_strain
            from .phase3_results import export_profiles, load_grid_run
            from .profiles import load_profiles, sample_profile
            saved = load_grid_run(args.run)
            strain = horizontal_strain(saved.surface, saved.displacement_m)
            profiles = tuple(sample_profile(saved.surface, saved.displacement_m, strain, line) for line in load_profiles(args.profiles))
            export_profiles(profiles, args.output, project=saved.project, model=saved.model, strain=strain, source_run=str(args.run))
            print(json.dumps({"output": args.output, "profile_count": len(profiles), "sampling": "saved displacement grid; influence solver not rerun"}, indent=2))
            return 0
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
        elif args.command in ("solve-flat", "solve-inclined"):
            from .results import export_displacements
            if args.command == "solve-inclined":
                from .inclined import solve_inclined
                model = load_model(args.model)
                solver = solve_inclined
            else:
                model, solver = load_flat_model(args.model), solve_flat
            surface = build_surface_grid(project)
            result = solver(project, model, surface.xyz_m, observation_chunk_size=args.observation_chunk_size, source_chunk_size=args.source_chunk_size)
            summary = export_displacements(project, model, surface, result, args.output)
            print(json.dumps({"output": args.output, "source_count": summary["source_count"], "evaluation_point_count": summary["evaluation_point_count"], "peak_sampled_settlement_m": summary["peak_sampled_settlement_m"], "status": summary["status"]}, indent=2))
        else:
            from .deformation import horizontal_strain
            from .phase3_results import export_deformation
            from .profiles import load_profiles, sample_profile
            if args.command == "deform-inclined":
                from .inclined import solve_inclined
                model = load_model(args.model)
                solver = solve_inclined
                kwargs = {"observation_chunk_size": args.observation_chunk_size, "source_chunk_size": args.source_chunk_size}
            else:
                model, solver, kwargs = load_flat_model(args.model), solve_flat, {}
            surface = build_surface_grid(project)
            # Check derivative feasibility before the potentially expensive solve.
            from .grid_fields import surface_axes
            surface_axes(surface, minimum_points=3)
            result = solver(project, model, surface.xyz_m, **kwargs)
            strain = horizontal_strain(surface, result.displacement_m)
            lines = load_profiles(args.profiles) if args.profiles else ()
            profiles = tuple(sample_profile(surface, result.displacement_m, strain, line) for line in lines)
            summary = export_deformation(project, model, surface, result, strain, args.output, profiles=profiles)
            print(json.dumps({"output": args.output, "profile_count": len(profiles), "boundary_cell_count": summary["boundary_cell_count"], "status": summary["status"]}, indent=2))
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 0
