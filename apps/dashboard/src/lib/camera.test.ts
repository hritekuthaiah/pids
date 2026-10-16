import { describe, expect, it } from "vitest";

import {
  DEFAULT_PREVIEW_URL,
  EDGE_PREVIEW_URL,
  attemptUrl,
  previewUrl,
  snapshotUrl,
} from "./camera";

describe("previewUrl", () => {
  it("defaults to the edge node's loopback stream", () => {
    expect(DEFAULT_PREVIEW_URL).toBe("http://127.0.0.1:8090/stream.mjpg");
    expect(previewUrl(undefined)).toBe(DEFAULT_PREVIEW_URL);
    expect(previewUrl("   ")).toBe(DEFAULT_PREVIEW_URL);
    // VITE_EDGE_PREVIEW_URL is unset under test
    expect(EDGE_PREVIEW_URL).toBe(DEFAULT_PREVIEW_URL);
  });

  it("uses the configured URL when set", () => {
    expect(previewUrl(" http://127.0.0.1:9000/stream.mjpg ")).toBe(
      "http://127.0.0.1:9000/stream.mjpg",
    );
  });
});

describe("attemptUrl", () => {
  it("leaves the first attempt alone and makes every retry distinct", () => {
    const url = "http://127.0.0.1:8090/stream.mjpg";
    expect(attemptUrl(url, 0)).toBe(url);
    expect(attemptUrl(url, 1)).toBe(`${url}?attempt=1`);
    expect(attemptUrl(`${url}?q=70`, 2)).toBe(`${url}?q=70&attempt=2`);
  });
});

describe("snapshotUrl", () => {
  it("points at the snapshot endpoint beside an edge stream", () => {
    expect(snapshotUrl("http://127.0.0.1:8090/stream.mjpg?attempt=3")).toBe(
      "http://127.0.0.1:8090/snapshot.jpg",
    );
    expect(snapshotUrl("http://localhost:8090/edge/stream.mjpg")).toBe(
      "http://localhost:8090/edge/snapshot.jpg",
    );
  });

  it("has nothing to probe for other sources or malformed URLs", () => {
    expect(snapshotUrl("http://camera.local/video.cgi")).toBeNull();
    expect(snapshotUrl("not a url")).toBeNull();
  });
});
