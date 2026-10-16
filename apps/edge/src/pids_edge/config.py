"""Edge-node configuration: one YAML file per node (``config/edge/<node>.yaml``).

Geometry (where the node stands, what the zones are) comes from the site file; this
file only says how *this* node turns pixels into telemetry. Secrets (MQTT password)
never live here — they come from the environment.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

Fraction = Annotated[float, Field(gt=0.0, lt=1.0)]


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CameraConfig(_Config):
    source: int | str = Field(
        default=0, description="device index, or a video file / RTSP URL for replay"
    )
    width: Annotated[int, Field(gt=0)] = 1280
    height: Annotated[int, Field(gt=0)] = 720
    fps: Annotated[float, Field(gt=0)] = 30.0


class DetectorConfig(_Config):
    model: Path = Path("apps/edge/models/yolo26n.onnx")
    score_threshold: Fraction = Field(
        default=0.1, description="lowest score kept — ByteTrack's second stage uses 0.1-0.5"
    )
    iou_threshold: Fraction = 0.6
    threads: Annotated[int, Field(ge=0)] = Field(default=0, description="0 = ONNX Runtime default")


class TrackerConfig(_Config):
    """ByteTrack parameters (Zhang et al., ECCV 2022) — defaults are the paper's."""

    high_threshold: Fraction = 0.5
    low_threshold: Fraction = 0.1
    new_track_threshold: Fraction = 0.6
    match_iou: Fraction = Field(default=0.2, description="first-stage minimum IoU")
    low_match_iou: Fraction = Field(default=0.5, description="second-stage minimum IoU")
    unconfirmed_match_iou: Fraction = 0.3
    lost_buffer_s: Annotated[float, Field(gt=0)] = 1.5


class GroundConfig(_Config):
    calibration: Path = Field(description="homography file written by `pids-edge calibrate`")
    max_range_factor: Annotated[float, Field(ge=1.0)] = Field(
        default=1.25, description="drop projections beyond this multiple of the node's range"
    )


class PublishConfig(_Config):
    rate_hz: Annotated[float, Field(gt=0, le=30)] = 5.0
    health_period_s: Annotated[float, Field(gt=0)] = 5.0
    replay_window_s: Annotated[float, Field(ge=0)] = Field(
        default=3.0,
        description="on reconnect, resend telemetry younger than this; older is stale",
    )
    buffer_limit: Annotated[int, Field(gt=0)] = 600


class PreviewConfig(_Config):
    enabled: bool = True
    host: str = Field(default="127.0.0.1", description="loopback only unless deliberately exposed")
    port: Annotated[int, Field(gt=0, lt=65536)] = 8090
    jpeg_quality: Annotated[int, Field(ge=10, le=95)] = 70


class GpsConfig(_Config):
    """A serial GPS module carried as a cooperative tag (PLT-03)."""

    driver: Literal["none", "serial"] = "none"
    port: str = Field(default="auto", description="device path, or auto-detect")
    baud: Annotated[int, Field(gt=0)] | None = Field(default=None, description="None = detect")
    tag_id: str | None = Field(default=None, description="registry tag this module reports as")


class ThermalSensorConfig(_Config):
    driver: Literal["none", "mlx90640"] = "none"
    delta_c: Annotated[float, Field(gt=0)] = Field(
        default=4.0, description="degrees above the frame median that count as warm"
    )


class BleConfig(_Config):
    """The node's Bluetooth radio as a passive badge reader (ADR-0012)."""

    driver: Literal["none", "bleak"] = "none"
    reader_id: str | None = Field(default=None, description="a `kind: ble` reader in the site file")
    allow_static: bool = Field(
        default=False, description="accept fixed (replayable) ids — bench testing only"
    )


class SensorsConfig(_Config):
    gps: GpsConfig = Field(default_factory=GpsConfig)
    thermal: ThermalSensorConfig = Field(default_factory=ThermalSensorConfig)
    ble: BleConfig = Field(default_factory=BleConfig)


class EdgeConfig(_Config):
    site: Path
    node_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")]
    camera: CameraConfig = Field(default_factory=CameraConfig)
    detector: DetectorConfig = Field(default_factory=DetectorConfig)
    tracker: TrackerConfig = Field(default_factory=TrackerConfig)
    ground: GroundConfig
    publish: PublishConfig = Field(default_factory=PublishConfig)
    preview: PreviewConfig = Field(default_factory=PreviewConfig)
    sensors: SensorsConfig = Field(default_factory=SensorsConfig)

    @model_validator(mode="after")
    def _ble_needs_a_reader(self) -> EdgeConfig:
        if self.sensors.ble.driver != "none" and not self.sensors.ble.reader_id:
            raise ValueError("sensors.ble.reader_id is required when a BLE driver is enabled")
        return self

    @model_validator(mode="after")
    def _gps_needs_a_tag(self) -> EdgeConfig:
        if self.sensors.gps.driver != "none" and not self.sensors.gps.tag_id:
            raise ValueError("sensors.gps.tag_id is required when a GPS driver is enabled")
        return self

    @model_validator(mode="after")
    def _thresholds_ordered(self) -> EdgeConfig:
        t = self.tracker
        if not t.low_threshold < t.high_threshold <= t.new_track_threshold:
            raise ValueError("need low_threshold < high_threshold <= new_track_threshold")
        if self.detector.score_threshold > t.low_threshold:
            raise ValueError("detector.score_threshold must not exceed tracker.low_threshold")
        return self

    @classmethod
    def from_yaml(cls, path: Path) -> EdgeConfig:
        with path.open(encoding="utf-8") as fh:
            return cls.model_validate(yaml.safe_load(fh))
