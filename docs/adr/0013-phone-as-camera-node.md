# ADR-0013: A phone can be the camera node

- **Status:** Accepted
- **Date:** 2026-10-17
- **Requirements:** AIL-01, NFR-04, NFR-07; extends ADR-0006 and ADR-0011

## Context

The demo laptop's built-in camera has to sit where the laptop sits, which is the
operator's desk — the worst place to watch a room from. A camera belongs high in a
corner, looking across the floor, which is exactly where a spare phone can be wedged.
The team has spare Android phones and no IP cameras, and the guard app is already
installed on them.

Nothing in the perception pipeline cares where frames come from: the edge node reads a
`cv2.VideoCapture` source, and the floor homography (ADR-0011) maps *that* camera's
pixels to the ground. So this is a question of how frames reach the edge node.

## Decision

**The edge node reads network camera streams as first-class sources.** A `camera.source`
beginning `http://`, `https://`, `rtsp://` or `rtmp://` is opened through FFMPEG with
RTSP forced over TCP (UDP sheds frames on wifi) and 5-second open and read timeouts, so
a phone that walks out of range is noticed in seconds instead of blocking the grabber.
Resolution and frame rate are left to whatever the phone sends — asking a decoder to
change them mid-stream only confuses it. The reconnect threshold is 3 failed reads for a
network source against 30 for USB, because each network failure already costs a timeout.
`pids-edge camera-test <url>` reports resolution, measured frame rate and dropped frames
before the demo, with a checklist when it cannot connect.

**The guard app can be that camera, with no third-party software.** A local Expo module
(`modules/pids-camera`, Kotlin) runs a `camera` foreground service: Camera2 preview
frames arrive as `YUV_420_888`, are packed to NV21 (row- and pixel-stride aware, because
planes are rarely tightly packed), JPEG-encoded, and served as
`multipart/x-mixed-replace` by a ~150-line HTTP server. It has one streaming path, a
snapshot and a health check, and nothing else. The guard screen shows the URLs the phone
can be reached on, in type large enough to read across a room.

**The phone announces itself; it never uploads video.** While streaming, the app POSTs
its stream URL to `/api/v1/devices/camera` every 30 s. The server keeps that in Redis
with a 90-second TTL and lists it on `/sites/{id}/cameras`, so the console can show the
operator where to point the edge node. Frames go straight from the phone to the edge over
the local network.

**A third-party IP-camera app remains supported** — it is just another URL — and is the
fallback if the in-app camera misbehaves on a particular phone.

## Alternatives considered

- *WebRTC from the app:* lower latency and NAT traversal, neither of which a single LAN
  needs, for a signalling server and a much larger dependency.
- *Uploading frames to the server, which fans them out:* doubles the hops and the
  latency, and puts video through a machine that has no reason to see it.
- *`expo-camera` with repeated `takePictureAsync`:* a few frames a second, shutter
  sounds, and no control over pacing.

## Consequences

- The camera can go where a camera should go, and the laptop can sit with the operator.
- Phones are the demo's weak link: battery (keep it plugged in), wifi, and thermal
  throttling. 1280x720 at 15 fps with JPEG quality 70 is the default for that reason.
- Streams are plain HTTP on the local network, like the edge preview (ADR-0011). MQTT
  telemetry is TLS; this is not, and must stay on a trusted network. TLS here would need
  a certificate per phone.
- Nothing is recorded on the phone and no video reaches the server (NFR-04).
- Moving the camera means recalibrating: the homography belongs to where the phone sits.
