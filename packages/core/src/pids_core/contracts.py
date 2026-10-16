"""Interface contracts — the single source of truth for every message in PIDS.

These models are the perception → decision seam fixed in PRD §7.1 and the
decision → client payloads. JSON Schema for each is exported to generate the
TypeScript types both clients compile against, so a contract change is a
compile error everywhere it matters.

Conventions:
- every timestamp is timezone-aware (naive datetimes are rejected);
- positions on the wire are WGS84; kinematics inside the core use ENU metres;
- ``trace`` carries the wall-clock time each pipeline hop handled the message,
  so end-to-end latency is measured rather than estimated (NFR-01).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

SCHEMA_VERSION: Literal[1] = 1

Probability = Annotated[float, Field(ge=0.0, le=1.0)]
NonNegative = Annotated[float, Field(ge=0.0)]
Trace = dict[str, AwareDatetime]


class Contract(BaseModel):
    """Base for wire models: immutable, unknown fields rejected."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        use_enum_values=False,
        # Output schemas mark defaulted fields as always present, so generated client
        # types don't treat e.g. `flags` as optional.
        json_schema_serialization_defaults_required=True,
    )


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class EntityClass(StrEnum):
    PERSON = "person"
    VEHICLE = "vehicle"
    ANIMAL = "animal"
    UNKNOWN = "unknown"


class ZoneKind(StrEnum):
    """``warning`` and ``critical`` nest for exclusion; ``containment`` homes tagged assets."""

    WARNING = "warning"
    CRITICAL = "critical"
    CONTAINMENT = "containment"


class TagKind(StrEnum):
    PERSON = "person"
    VEHICLE = "vehicle"
    ASSET = "asset"


class ThreatLevel(StrEnum):
    NOMINAL = "nominal"
    ELEVATED = "elevated"
    WARNING = "warning"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return _LEVEL_RANK[self]

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, ThreatLevel):
            return NotImplemented
        return self.rank < other.rank

    def __le__(self, other: object) -> bool:
        if not isinstance(other, ThreatLevel):
            return NotImplemented
        return self.rank <= other.rank

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, ThreatLevel):
            return NotImplemented
        return self.rank > other.rank

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, ThreatLevel):
            return NotImplemented
        return self.rank >= other.rank


_LEVEL_RANK = {
    ThreatLevel.NOMINAL: 0,
    ThreatLevel.ELEVATED: 1,
    ThreatLevel.WARNING: 2,
    ThreatLevel.CRITICAL: 3,
}


class AlertEventKind(StrEnum):
    RAISED = "raised"
    ESCALATED = "escalated"
    CLEARED = "cleared"
    TRACK_LOST = "track_lost"


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


class GeoPoint(Contract):
    lat: Annotated[float, Field(ge=-90.0, le=90.0)]
    lon: Annotated[float, Field(ge=-180.0, le=180.0)]


class Velocity(Contract):
    """Ground velocity in the site frame, metres per second."""

    east: float
    north: float


# ---------------------------------------------------------------------------
# Perception -> decision (edge node or simulator -> decision engine)
# ---------------------------------------------------------------------------


class VisionTrack(Contract):
    """One tracked object from one camera node in one perception cycle (PRD §7.1)."""

    track_id: Annotated[str, Field(min_length=1, max_length=64)]
    entity_class: EntityClass
    class_confidence: Probability
    position: GeoPoint
    position_sigma_m: NonNegative = Field(description="1-sigma ground-plane localisation error")
    velocity: Velocity | None = None
    hits: Annotated[int, Field(ge=1)] = Field(description="frames this track has been matched")
    thermal_confirmed: bool | None = Field(
        default=None,
        description="Heat signature at this track's bearing. None = no thermal coverage.",
    )
    anomaly_score: Probability | None = Field(
        default=None, description="Optional edge-computed score; otherwise computed downstream."
    )


class TrackBatch(Contract):
    """Everything one edge node tracked in one perception cycle."""

    schema_version: Literal[1] = SCHEMA_VERSION
    site_id: str
    node_id: str
    captured_at: AwareDatetime
    tracks: list[VisionTrack]
    trace: Trace = Field(default_factory=dict)


class GpsFix(Contract):
    """A position report from a cooperative GPS tag (GPS module or guard phone)."""

    schema_version: Literal[1] = SCHEMA_VERSION
    site_id: str
    tag_id: str
    at: AwareDatetime
    position: GeoPoint
    accuracy_m: NonNegative
    hdop: NonNegative | None = None
    satellites: Annotated[int, Field(ge=0)] | None = None
    trace: Trace = Field(default_factory=dict)


class TagRead(Contract):
    """A short-range RFID/BLE read of a cooperative tag at a fixed reader."""

    schema_version: Literal[1] = SCHEMA_VERSION
    site_id: str
    reader_id: str
    tag_id: str
    at: AwareDatetime
    rssi_dbm: float | None = None
    trace: Trace = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Decision -> clients
# ---------------------------------------------------------------------------


class ChannelContribution(Contract):
    """How much one evidence channel moved the fused log-odds (for explanation)."""

    channel: str
    value: float | None = Field(description="the evidence term fed to fusion; None = unavailable")
    log_odds: float


class ThreatAssessment(Contract):
    """The decision core's judgement about one entity at one instant."""

    schema_version: Literal[1] = SCHEMA_VERSION
    site_id: str
    entity_id: str
    at: AwareDatetime
    entity_class: EntityClass
    position: GeoPoint
    velocity: Velocity | None
    zone_id: str | None
    zone_kind: ZoneKind | None
    probability: Probability
    score: Annotated[int, Field(ge=0, le=100)]
    level: ThreatLevel
    contributions: list[ChannelContribution]
    tag_id: str | None = None
    authorized: bool = False
    spoof_suspicion: Probability = 0.0
    anomaly_score: Probability | None = None
    time_to_breach_s: NonNegative | None = None
    predicted_zone_id: str | None = None
    flags: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list, description="e.g. vision:edge-01, gps:tag-7")
    trace: Trace = Field(default_factory=dict)


class AlertEvent(Contract):
    """A change in an entity's alert state, emitted by the alert state machine."""

    schema_version: Literal[1] = SCHEMA_VERSION
    alert_id: str
    kind: AlertEventKind
    level: ThreatLevel
    previous_level: ThreatLevel | None
    at: AwareDatetime
    reason: str
    assessment: ThreatAssessment
