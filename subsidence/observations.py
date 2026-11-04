"""Station measurements with explicit datum, sign, stage and split provenance."""

import csv
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path

from .config import _keys, _reject_constant, _unique_object
from .geometry import ValidationError, finite_number


@dataclass(frozen=True)
class ObservationMetadata:
    name: str
    evidence: str
    vertical_sign: str
    coordinate_reference: str
    vertical_datum: str
    measurement_stage: str
    provenance: str
    line_roles: dict
    reported_rmse_m_by_line: dict
    reported_metrics_source: str = ""

    @classmethod
    def from_dict(cls, data):
        required = ("schema_version", "units", "name", "evidence", "vertical_sign", "coordinate_reference", "vertical_datum", "measurement_stage", "provenance", "line_roles")
        _keys(data, required, ("reported_rmse_m_by_line", "reported_metrics_source"), label="observation metadata")
        if type(data["schema_version"]) is not int or data["schema_version"] != 1 or data["units"] != {"length": "m"}:
            raise ValidationError("Observation metadata requires schema_version 1 and units.length='m'.")
        for name in ("name", "coordinate_reference", "vertical_datum", "measurement_stage", "provenance"):
            if not isinstance(data[name], str) or not data[name].strip():
                raise ValidationError(f"Observation {name} must be documented as a nonempty string.")
        if data["evidence"] not in ("field_measurements", "digitized_with_survey_coordinates", "synthetic_verification"):
            raise ValidationError("Observation evidence must explicitly identify field, digitized-with-coordinates, or synthetic data.")
        if data["vertical_sign"] not in ("up_positive", "settlement_positive"):
            raise ValidationError("vertical_sign must be up_positive or settlement_positive.")
        roles = data["line_roles"]
        if not isinstance(roles, dict) or not roles or any(not isinstance(k, str) or not k.strip() or v not in ("fit", "test") for k, v in roles.items()):
            raise ValidationError("line_roles must map nonempty line IDs to fit or test.")
        if set(roles.values()) != {"fit", "test"}:
            raise ValidationError("A baseline comparison requires separate fit and test lines.")
        reported = data.get("reported_rmse_m_by_line", {})
        if not isinstance(reported, dict) or set(reported) - set(roles):
            raise ValidationError("Reported RMSE keys must refer to declared lines.")
        reported = {key: finite_number(value, "reported RMSE") for key, value in reported.items()}
        if any(v < 0 for v in reported.values()):
            raise ValidationError("Reported RMSE cannot be negative.")
        source = data.get("reported_metrics_source", "")
        if not isinstance(source, str) or (reported and not source.strip()):
            raise ValidationError("Reported metrics require a documented source.")
        return cls(*(data[k] for k in ("name", "evidence", "vertical_sign", "coordinate_reference", "vertical_datum", "measurement_stage", "provenance")), dict(roles), reported, source)

    def to_dict(self):
        return {"schema_version": 1, "units": {"length": "m"}, **self.__dict__}


@dataclass(frozen=True)
class StationObservation:
    station_id: str
    line_id: str
    x_m: float
    y_m: float
    uz_input_m: float
    uz_observed_m: float             # Canonical z upward after declared sign conversion.
    distance_m: float | None = None
    uncertainty_m: float | None = None


@dataclass(frozen=True)
class ObservationDataset:
    metadata: ObservationMetadata
    stations: tuple[StationObservation, ...]
    raw_csv: bytes
    raw_metadata: bytes

    @property
    def csv_sha256(self):
        return hashlib.sha256(self.raw_csv).hexdigest()


def load_observations(csv_path: str | Path, metadata_path: str | Path) -> ObservationDataset:
    raw_metadata = Path(metadata_path).read_bytes()
    data = json.loads(raw_metadata.decode("utf-8-sig"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    metadata = ObservationMetadata.from_dict(data)
    raw_csv = Path(csv_path).read_bytes()
    reader = csv.DictReader(io.StringIO(raw_csv.decode("utf-8-sig"), newline=""))
    required = {"station_id", "line_id", "x_m", "y_m", "uz_observed_m"}
    allowed = required | {"distance_m", "uncertainty_m"}
    header = reader.fieldnames
    if not header or len(set(header)) != len(header) or required - set(header) or set(header) - allowed:
        raise ValidationError("Observation CSV requires station_id,line_id,x_m,y_m,uz_observed_m; optional distance_m,uncertainty_m; duplicate/unknown columns are rejected.")
    records, ids = [], set()
    for row_number, row in enumerate(reader, start=2):
        if None in row or any(v is None for v in row.values()):
            raise ValidationError(f"Observation CSV row {row_number} has an inconsistent column count.")
        station_id, line_id = row["station_id"].strip(), row["line_id"].strip()
        if not station_id or station_id in ids:
            raise ValidationError(f"Empty or duplicate station_id on row {row_number}; fit/test station IDs must be distinct.")
        if line_id not in metadata.line_roles:
            raise ValidationError(f"Unknown line_id '{line_id}' on row {row_number}.")

        def number(name, optional=False):
            value = row.get(name, "").strip()
            if optional and not value:
                return None
            try:
                return finite_number(float(value), f"{name} on row {row_number}")
            except ValueError as exc:
                raise ValidationError(f"{name} on row {row_number} must be a finite number.") from exc

        x, y, observed = number("x_m"), number("y_m"), number("uz_observed_m")
        distance, uncertainty = number("distance_m", True), number("uncertainty_m", True)
        if (distance is not None and distance < 0) or (uncertainty is not None and uncertainty < 0):
            raise ValidationError(f"Distance/uncertainty must be nonnegative on row {row_number}.")
        canonical = observed if metadata.vertical_sign == "up_positive" else -observed
        records.append(StationObservation(station_id, line_id, x, y, observed, canonical, distance, uncertainty))
        ids.add(station_id)
    if not records:
        raise ValidationError("No station observations are available. Supply measured coordinates/Uz; the template intentionally contains no invented data.")
    for line_id in metadata.line_roles:
        line = [r for r in records if r.line_id == line_id]
        if not line:
            raise ValidationError(f"Declared line '{line_id}' has no observations.")
        distances = [r.distance_m for r in line]
        if any(d is None for d in distances) and any(d is not None for d in distances):
            raise ValidationError(f"Line '{line_id}' mixes missing and available distances.")
        if distances[0] is not None and len(set(distances)) != len(distances):
            raise ValidationError(f"Line '{line_id}' has duplicate distances.")
    return ObservationDataset(metadata, tuple(records), raw_csv, raw_metadata)
