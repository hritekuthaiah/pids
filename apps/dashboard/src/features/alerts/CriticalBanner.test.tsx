import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useLive } from "../../state/live";
import { alert } from "../../test/fixtures";
import { CriticalBanner } from "./CriticalBanner";

const { start, stop } = vi.hoisted(() => ({ start: vi.fn(), stop: vi.fn() }));
vi.mock("../../lib/alarm", () => ({ alarm: { start, stop } }));
vi.mock("../../lib/api", () => ({ pids: { api: { POST: vi.fn() } } }));

function renderBanner() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <CriticalBanner />
    </QueryClientProvider>,
  );
}

describe("CriticalBanner", () => {
  beforeEach(() => {
    start.mockClear();
    stop.mockClear();
    useLive.getState().reset();
    useLive.setState({ muted: false });
  });

  it("stays hidden and silent without an unacknowledged critical alert", () => {
    useLive.getState().apply({ type: "alerts_snapshot", alerts: [alert("w", "warning")] });
    renderBanner();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(start).not.toHaveBeenCalled();
  });

  it("shows the breach and sounds the alarm for an open critical alert", () => {
    useLive.getState().apply({ type: "alerts_snapshot", alerts: [alert("c", "critical")] });
    renderBanner();
    expect(screen.getByRole("alert")).toHaveTextContent("CRITICAL BREACH");
    expect(start).toHaveBeenCalled();
  });

  it("goes quiet once the operator acknowledges", () => {
    useLive.getState().apply({ type: "alerts_snapshot", alerts: [alert("c", "critical")] });
    renderBanner();
    act(() => {
      useLive.getState().apply({
        type: "alert",
        event: "acknowledged",
        alert: alert("c", "critical", { status: "acknowledged" }),
      });
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(stop).toHaveBeenCalled();
  });

  it("respects mute without hiding the banner", () => {
    useLive.setState({ muted: true });
    useLive.getState().apply({
      type: "alerts_snapshot",
      alerts: [alert("c1", "critical"), alert("c2", "critical")],
    });
    renderBanner();
    expect(screen.getByRole("alert")).toHaveTextContent("×2");
    expect(start).not.toHaveBeenCalled();
  });
});
