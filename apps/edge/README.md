# pids-edge — camera edge node

Turns a camera into `TrackBatch` telemetry for the decision core (ADR-0011):

```
camera ─▶ YOLO26n (ONNX Runtime, CPU) ─▶ ByteTrack ─▶ floor homography ─▶ MQTT
                                                   └▶ annotated preview (loopback MJPEG)
```

It runs natively, not in Docker: Docker Desktop on macOS cannot reach USB cameras
(ADR-0006).

## One-time setup

```bash
make edge-model      # export yolo26n.onnx into apps/edge/models/ (isolated env, ~2 min)
make edge-cameras    # which camera index is which
```

The first camera access asks macOS for permission for the app running the command
(Terminal, or Claude). Allow it in **System Settings → Privacy & Security → Camera**.

## Calibrate the floor (once per camera position)

Positions are site metres from `config/sites/demo-room.yaml` (origin: the room's
south-west floor corner). Edit `config/edge/edge-01.marks.yaml` to the real marks.

**Markers (recommended).** Print the markers, lay each one centred on its surveyed
point, then run:

```bash
uv run pids-edge markers --out markers --ids 0-5      # print at 15-20 cm
uv run pids-edge calibrate --marks config/edge/edge-01.marks.yaml
```

Press SPACE when every marker shows a green cross. The tool fits the homography,
prints its RMS error and draws the zones back onto the image. Check that they sit on
the taped floor, then press Y to save `config/edge/edge-01.calibration.yaml`.

**Tape marks.** Same command with `--mode click`. Freeze the frame, then click each
mark in the order listed.

**No marks yet.** Use a rough estimate from the mounting:
`uv run pids-edge calibrate-pose --height 2.4 --pitch 30 --hfov 70`

## Run

```bash
make up-all          # stack (use PIDS_SITE_CONFIG=config/sites/demo-room.yaml for the room)
make edge            # loads MQTT credentials from .env
```

Open the preview at <http://127.0.0.1:8090/stream.mjpg> and status at `/status`.
Frames are shown live and never stored. `uv run pids-edge run --source clip.mp4`
replays a recording through the same pipeline.

## GPS module

Plug it in and run `make gps-probe`. It tries each serial port at each common baud
rate and keeps the first that gives checksum-valid NMEA. It then reports the module
as far as the module describes itself (u-blox and others announce hardware and
firmware over `$GPTXT`), and says whether it already has a position fix. Most modules
work: u-blox NEO-6M/7M/M8N/M10, Quectel, MediaTek, and USB pucks like the VK-162.

To use it, set `sensors.gps.driver: serial` in `config/edge/edge-01.yaml`. Fixes are
published as `GpsFix` for tag `gps-puck-1`. `make gps` streams them without a camera,
e.g. from a laptop carried outdoors. The accuracy estimate is HDOP × 4 m (UERE),
floored at 2.5 m.

## BLE badges (team phones)

`sensors.ble.driver: bleak` turns the laptop's Bluetooth into a passive badge reader
(ADR-0012). It listens for rolling PIDS identifiers, resolves them with
`PIDS_BADGE_KEY` from `.env`, and publishes smoothed `TagRead`s with RSSI. The decision
core links a badge to a person only when the RSSI clearly follows that person's
motion. `uv run pids-edge ble` lists the badges it hears. macOS asks for Bluetooth
permission for the app running it.

The guard app advertises the rolling identifier. For bench testing before that, a
generic BLE advertiser app can broadcast a fixed id. Get it with
`pids-edge badge-code badge-team-1`, then set `sensors.ble.allow_static: true` on
that machine. A fixed id is replayable, so never use one at the demo.

## Thermal

`sensors.thermal.driver: mlx90640` reads a Melexis MLX90640 over I2C on a Pi. Each
track's bearing is checked for heat at least 4 °C above the frame median, and the
result is published as `thermal_confirmed`. With no array fitted, the value is `None`,
which fusion treats as neutral. The live demo runs without thermal: `SyntheticThermal`
exists for tests only.

## Tests

`uv run pytest apps/edge` covers the following. A synthetic pinhole camera looks at
the demo room, so the whole chain is checked to centimetres:

- decoding of both YOLO export layouts, plus NMS;
- ByteTrack behaviour: occlusion, ghosts, crossings, and the lost-track buffer;
- CLEAR-MOT ID-switch counting;
- homography fitting, including RANSAC against a misclicked mark;
- uncertainty propagation;
- ArUco calibration on rendered marker images;
- the outbox;
- `EdgeNode.process` end to end.
