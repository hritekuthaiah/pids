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
