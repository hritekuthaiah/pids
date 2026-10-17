import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { pids } from "../../lib/api";
import { useLive } from "../../state/live";
import { CameraPanel } from "./CameraPanel";

const STREAM = "http://127.0.0.1:8090/stream.mjpg";

// Liveness probes are created with `new Image()`; keep them so tests can answer them.
let probes: HTMLImageElement[] = [];

function advance(ms: number) {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

/** The panel asks the API where its camera is looking, so it needs query context. */
function renderPanel(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: Infinity } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const feed = () => screen.queryByRole("img");
const status = () => screen.getByRole("status");

function goLive() {
  renderPanel(<CameraPanel url={STREAM} />);
  const img = feed();
  if (!img) throw new Error("no feed");
  fireEvent.load(img);
}

describe("CameraPanel", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    probes = [];
    const RealImage = window.Image;
    vi.stubGlobal(
      "Image",
      class extends RealImage {
        constructor() {
          super();
          probes.push(this);
        }
      },
    );
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("embeds the edge preview as an image and goes live on the first frame", () => {
    renderPanel(<CameraPanel url={STREAM} />);
    const img = feed();
    expect(img).toHaveAttribute("src", STREAM);
    expect(status()).toHaveTextContent("connecting");
    fireEvent.load(img as HTMLImageElement);
    expect(status()).toHaveTextContent("live");
    expect(img).toBeVisible();
  });

  it("defaults to the edge node's loopback stream", () => {
    renderPanel(<CameraPanel />);
    expect(feed()).toHaveAttribute("src", STREAM);
  });

  it("shows camera offline when the image errors, then retries every 3 s", () => {
    renderPanel(<CameraPanel url={STREAM} />);
    fireEvent.error(feed() as HTMLImageElement);
    expect(status()).toHaveTextContent("offline");
    expect(screen.getByText("Camera offline")).toBeInTheDocument();
    expect(screen.getByText(/preview is unreachable/)).toBeInTheDocument();
    expect(feed()).not.toBeInTheDocument();

    advance(2999);
    expect(feed()).not.toBeInTheDocument();
    advance(1);
    expect(feed()).toHaveAttribute("src", `${STREAM}?attempt=1`);
    expect(status()).toHaveTextContent("connecting");

    fireEvent.error(feed() as HTMLImageElement);
    expect(screen.getByText(/attempt 2/)).toBeInTheDocument();
    advance(3000);
    fireEvent.load(feed() as HTMLImageElement);
    expect(feed()).toHaveAttribute("src", `${STREAM}?attempt=2`);
    expect(status()).toHaveTextContent("live");
  });

  it("retries at once on request", () => {
    renderPanel(<CameraPanel url={STREAM} />);
    fireEvent.error(feed() as HTMLImageElement);
    fireEvent.click(screen.getByRole("button", { name: "Retry now" }));
    expect(feed()).toHaveAttribute("src", `${STREAM}?attempt=1`);
  });

  it("gives up on a stream that never delivers a first frame", () => {
    renderPanel(<CameraPanel url={STREAM} />);
    advance(8000);
    expect(status()).toHaveTextContent("offline");
    expect(screen.getByText(/sending no frames/)).toBeInTheDocument();
    advance(3000);
    expect(feed()).toHaveAttribute("src", `${STREAM}?attempt=1`);
  });

  it("probes the edge while live and goes offline when it stops answering", () => {
    goLive();
    expect(probes).toHaveLength(0);
    advance(5000);
    expect(probes).toHaveLength(1);
    expect(probes[0]?.src).toMatch(/^http:\/\/127\.0\.0\.1:8090\/snapshot\.jpg\?t=\d+$/);

    act(() => {
      probes[0]?.dispatchEvent(new Event("load"));
    });
    advance(5000);
    expect(probes).toHaveLength(2);
    expect(status()).toHaveTextContent("live");

    act(() => {
      probes[1]?.dispatchEvent(new Event("error"));
    });
    expect(status()).toHaveTextContent("offline");
    expect(feed()).not.toBeInTheDocument();
  });

  it("treats a probe still unanswered at the next tick as a dead edge", () => {
    goLive();
    advance(5000);
    expect(status()).toHaveTextContent("live");
    advance(5000);
    expect(status()).toHaveTextContent("offline");
    expect(probes).toHaveLength(1);
  });

  it("does not probe sources other than an edge stream", () => {
    renderPanel(<CameraPanel url="http://camera.local/video.cgi" />);
    fireEvent.load(feed() as HTMLImageElement);
    advance(20_000);
    expect(probes).toHaveLength(0);
    expect(status()).toHaveTextContent("live");
  });

  it("closes the stream when collapsed and reconnects on expand", () => {
    goLive();
    const toggle = screen.getByRole("button", { name: "Collapse" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    fireEvent.click(toggle);
    expect(feed()).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByText(/stream is closed/)).toBeInTheDocument();
    advance(20_000);
    expect(probes).toHaveLength(0);
    expect(feed()).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Expand" }));
    expect(screen.getByRole("button", { name: "Collapse" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(feed()).toHaveAttribute("src", `${STREAM}?attempt=1`);
    expect(status()).toHaveTextContent("connecting");
  });

  it("stops retrying while collapsed", () => {
    renderPanel(<CameraPanel url={STREAM} />);
    fireEvent.error(feed() as HTMLImageElement);
    fireEvent.click(screen.getByRole("button", { name: "Collapse" }));
    advance(30_000);
    expect(feed()).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Expand" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });
});

describe("locating a point from the camera image", () => {
  const VIEW = {
    schema_version: 1,
    site_id: "demo-room",
    node_id: "edge-01",
    at: "2026-10-27T10:00:00Z",
    image_size: [1280, 720],
    homography: [
      [0.022473367, -0.0, -14.382954926],
      [-0.0, -0.010550607, 21.934834705],
      [0.0, 0.007937122, 1.0],
    ],
    footprint: [
      { lat: 13.262, lon: 77.42 },
      { lat: 13.2621, lon: 77.42 },
      { lat: 13.2621, lon: 77.4201 },
    ],
    origin: { lat: 13.262, lon: 77.42 },
    calibration_method: "aruco",
    calibration_rms_m: 0.02,
  };

  beforeEach(() => {
    vi.useRealTimers();
    useLive.getState().pin(null);
    vi.spyOn(pids.api, "GET").mockResolvedValue({ data: [VIEW] });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("pins where a clicked pixel is on the ground", async () => {
    renderPanel(<CameraPanel url={STREAM} siteId="demo-room" />);
    const img = feed() as HTMLImageElement;
    fireEvent.load(img);
    // the hint appears once the console knows where this camera is looking
    expect(await screen.findByText(/Click the image/)).toBeInTheDocument();

    // jsdom gives every element a zero box, so state the drawn area explicitly
    vi.spyOn(img, "getBoundingClientRect").mockReturnValue({
      left: 0,
      top: 0,
      width: 1280,
      height: 720,
      right: 1280,
      bottom: 720,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    });
    fireEvent.click(img, { clientX: 640, clientY: 713 });

    const pinned = useLive.getState().pinned;
    expect(pinned?.lngLat[1]).toBeGreaterThan(VIEW.origin.lat); // north of the origin
    expect(pinned?.label).toMatch(/m E, 2\.\d m N/);
    expect(screen.getByText(/13\.2620\d\d, 77\.4200\d\d/)).toBeInTheDocument();
  });

  it("says so when the click is above the horizon", async () => {
    // A shallower camera (15 deg down) puts the horizon at row ~115, inside the frame.
    const shallow = {
      ...VIEW,
      homography: [
        [-0.022488308, -0.0, 14.392517132],
        [-0.0, 0.005820402, -21.949606989],
        [0.0, -0.008688815, 1.0],
      ],
    };
    vi.spyOn(pids.api, "GET").mockResolvedValue({ data: [shallow] });
    renderPanel(<CameraPanel url={STREAM} siteId="demo-room" />);
    const img = feed() as HTMLImageElement;
    fireEvent.load(img);
    await screen.findByText(/Click the image/);
    vi.spyOn(img, "getBoundingClientRect").mockReturnValue({
      left: 0,
      top: 0,
      width: 1280,
      height: 720,
      right: 1280,
      bottom: 720,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    });

    fireEvent.click(img, { clientX: 640, clientY: 700 }); // floor, well below the horizon
    expect(useLive.getState().pinned).not.toBeNull();

    fireEvent.click(img, { clientX: 640, clientY: 40 }); // sky, above row 115
    expect(useLive.getState().pinned).toBeNull();
    expect(screen.getByText(/above the horizon/)).toBeInTheDocument();
  });
});
