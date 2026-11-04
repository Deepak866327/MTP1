"""Geometry foundation; displacement and strain solvers belong to later phases."""

from .config import Project, load_project, save_project
from .geometry import Rectangle, SeamPlane, ValidationError
from .mesh import SourceMesh, SurfaceGrid, build_source_mesh, build_surface_grid

__version__ = "0.1.0"
__all__ = [
    "Project", "Rectangle", "SeamPlane", "ValidationError", "SourceMesh",
    "SurfaceGrid", "load_project", "save_project", "build_source_mesh",
    "build_surface_grid",
]
