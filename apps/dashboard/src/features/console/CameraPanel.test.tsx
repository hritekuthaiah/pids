import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CameraPanel } from "./CameraPanel";

const STREAM = "http://127.0.0.1:8090/stream.mjpg";

// Liveness probes are created with `new Image()`; keep them so tests can answer them.
let probes: HTMLImageElement[] = [];

function advance(ms: number) {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

const feed = () => screen.queryByRole("img");
const status = () => screen.getByRole("status");

function goLive() {
  render(<CameraPanel url={STREAM} />);
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
    render(<CameraPanel url={STREAM} />);
    const img = feed();
    expect(img).toHaveAttribute("src", STREAM);
    expect(status()).toHaveTextContent("connecting");
    fireEvent.load(img as HTMLImageElement);
    expect(status()).toHaveTextContent("live");
    expect(img).toBeVisible();
  });

  it("defaults to the edge node's loopback stream", () => {
    render(<CameraPanel />);
    expect(feed()).toHaveAttribute("src", STREAM);
  });

  it("shows camera offline when the image errors, then retries every 3 s", () => {
    render(<CameraPanel url={STREAM} />);
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
    render(<CameraPanel url={STREAM} />);
    fireEvent.error(feed() as HTMLImageElement);
    fireEvent.click(screen.getByRole("button", { name: "Retry now" }));
    expect(feed()).toHaveAttribute("src", `${STREAM}?attempt=1`);
  });

  it("gives up on a stream that never delivers a first frame", () => {
    render(<CameraPanel url={STREAM} />);
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
    render(<CameraPanel url="http://camera.local/video.cgi" />);
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
    render(<CameraPanel url={STREAM} />);
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
