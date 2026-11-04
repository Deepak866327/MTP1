"""Flat/gently inclined displacement, geometry, global strains and profiles."""

from .config import FlatModel, InclinedModel, Project, load_flat_model, load_model, load_project, save_flat_model, save_model, save_project
from .geometry import Rectangle, SeamPlane, ValidationError
from .mesh import SourceMesh, SurfaceGrid, build_source_mesh, build_surface_grid
from .solver import DisplacementResult, solve_flat
from .deformation import StrainResult, horizontal_strain
from .profiles import ProfileLine, ProfileResult, load_profiles, sample_profile, save_profiles
from .inclined import solve_inclined
from .seam_frame import SeamFrame

__version__ = "0.4.0"
__all__ = [
    "Project", "Rectangle", "SeamPlane", "ValidationError", "SourceMesh",
    "SurfaceGrid", "load_project", "save_project", "build_source_mesh",
    "build_surface_grid",
    "FlatModel", "load_flat_model", "save_flat_model", "DisplacementResult", "solve_flat",
    "StrainResult", "horizontal_strain", "ProfileLine", "ProfileResult",
    "load_profiles", "sample_profile", "save_profiles",
    "InclinedModel", "load_model", "save_model", "solve_inclined", "SeamFrame",
]
