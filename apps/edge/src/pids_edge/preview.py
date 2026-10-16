"""Live annotated preview: an MJPEG stream for the operator's camera panel.

Served on loopback by default. Frames are encoded only while someone is watching,
held in memory only, and never written to disk — raw imagery is not stored
(NFR-04, India DPDP Act data minimisation).
"""

from __future__ import annotations

import json
import logging
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

import cv2
import numpy as np
from numpy.typing import NDArray

log = logging.getLogger("pids_edge.preview")

_BOUNDARY = "pidsframe"


class PreviewServer:
    def __init__(self, host: str, port: int, jpeg_quality: int = 70) -> None:
        self._quality = jpeg_quality
        self._cond = threading.Condition()
        self._jpeg: bytes | None = None
        self._seq = 0
        self._viewers = 0
        self.status: dict[str, Any] = {}
        self.allowed_hosts = {"127.0.0.1", "localhost", "::1", host}
        server = self

        class Handler(_Handler):
            preview: ClassVar[PreviewServer] = server

        self._httpd = ThreadingHTTPServer((host, port), Handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="preview", daemon=True
        )
        self.url = f"http://{host}:{port}/stream.mjpg"

    @property
    def watched(self) -> bool:
        return self._viewers > 0

    def start(self) -> None:
        self._thread.start()
        log.info("preview at %s", self.url)

    def submit(self, image: NDArray[np.uint8]) -> None:
        ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, self._quality])
        if not ok:
            return
        with self._cond:
            self._jpeg = buf.tobytes()
            self._seq += 1
            self._cond.notify_all()

    def wait_frame(self, after: int, timeout: float = 5.0) -> tuple[int, bytes | None]:
        with self._cond:
            self._cond.wait_for(lambda: self._seq != after, timeout)
            return self._seq, self._jpeg

    def viewer(self, delta: int) -> None:
        with self._cond:
            self._viewers += delta

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


class _Handler(BaseHTTPRequestHandler):
    preview: ClassVar[PreviewServer]
    server_version = "pids-edge"

    def log_message(self, format: str, *args: Any) -> None:
        log.debug(format, *args)

    def _no_store(self) -> None:
        # Deliberately no CORS header: the console embeds the stream as an <img>, which
        # needs none, while other origins' scripts stay unable to read the pixels.
        self.send_header("Cache-Control", "no-store")

    def do_GET(self) -> None:
        # Defeat DNS rebinding: a hostile page that rebinds its name to 127.0.0.1
        # would otherwise be same-origin with the camera.
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in self.preview.allowed_hosts:
            self.send_error(HTTPStatus.FORBIDDEN, "unexpected Host")
            return
        path = self.path.split("?", 1)[0]
        if path == "/stream.mjpg":
            self._stream()
        elif path == "/snapshot.jpg":
            _, jpeg = self.preview.wait_frame(-1, timeout=0)
            if jpeg is None:
                self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "no frame yet")
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(jpeg)))
            self._no_store()
            self.end_headers()
            self.wfile.write(jpeg)
        elif path == "/status":
            body = json.dumps(self.preview.status, default=str).encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self._no_store()
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def _stream(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={_BOUNDARY}")
        self._no_store()
        self.end_headers()
        self.preview.viewer(+1)
        seq = -1
        try:
            while True:
                seq, jpeg = self.preview.wait_frame(seq)
                if jpeg is None:
                    continue
                self.wfile.write(
                    f"--{_BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                    f"Content-Length: {len(jpeg)}\r\n\r\n".encode()
                )
                self.wfile.write(jpeg)
                self.wfile.write(b"\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.preview.viewer(-1)
