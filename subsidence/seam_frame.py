"""Continuous right-handed local/global coordinates for an upward seam normal."""

from dataclasses import dataclass

import numpy as np

from .geometry import SeamPlane, ValidationError


@dataclass(frozen=True)
class SeamFrame:
    seam: SeamPlane

    @property
    def basis(self) -> np.ndarray:
        """Columns are local unit x, y, normal expressed in global coordinates.

        The minimal rotation carrying global +z to n avoids a strike-axis
        singularity at zero dip. This matrix is exactly identity for a flat seam.
        """
        nx, ny, nz = self.seam.unit_normal
        c = 1 + nz
        return np.array([[1 - nx * nx / c, -nx * ny / c, nx], [-nx * ny / c, 1 - ny * ny / c, ny], [-nx, -ny, nz]])

    @staticmethod
    def _values(values) -> np.ndarray:
        array = np.asarray(values)
        if array.ndim < 1 or array.shape[-1] != 3 or array.dtype.kind not in "iuf" or not np.all(np.isfinite(array)):
            raise ValidationError("Coordinate/vector values must be finite numeric (...,3) arrays.")
        return np.asarray(array, dtype=float)

    def points_to_local(self, xyz_m) -> np.ndarray:
        return (self._values(xyz_m) - self.seam.reference_xyz_m) @ self.basis

    def points_to_global(self, local_xyz_m) -> np.ndarray:
        return self._values(local_xyz_m) @ self.basis.T + self.seam.reference_xyz_m

    def vectors_to_local(self, vectors) -> np.ndarray:
        return self._values(vectors) @ self.basis

    def vectors_to_global(self, vectors) -> np.ndarray:
        return self._values(vectors) @ self.basis.T
