import type { ThreatAssessment } from "@pids/api-client";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { useLive } from "../../state/live";
import { assessment } from "../../test/fixtures";
import { BaselinePanel } from "./BaselinePanel";

function snapshot(entities: ThreatAssessment[], at = "2026-10-27T04:30:00Z") {
  act(() => {
    useLive.getState().apply({ type: "live", site_id: "demo-room", at, entities });
  });
}

const column = (name: string) => within(screen.getByRole("group", { name }));
const NAIVE = "Naive geofence (would alarm)";
const PIDS = "PIDS (alerting)";

const teammate = assessment({
  entity_id: "edge-01/a-1",
  zone_id: "room-warning",
  level: "nominal",
  tag_id: "badge-7",
  authorized: true,
});
const intruder = assessment({
  entity_id: "edge-01/a-2",
  zone_id: "secure-core",
  level: "critical",
});

describe("BaselinePanel", () => {
  beforeEach(() => {
    useLive.getState().reset();
  });

  it("starts empty, waiting for live data", () => {
    render(<BaselinePanel />);
    expect(column(NAIVE).getByText("0")).toBeInTheDocument();
    expect(column(PIDS).getByText("0")).toBeInTheDocument();
    expect(screen.getByText("Awaiting data")).toBeInTheDocument();
    expect(screen.getByText(/No zone entries yet/)).toBeInTheDocument();
  });

  it("shows the naive geofence alarming on everyone in a zone and PIDS on the intruder", () => {
    render(<BaselinePanel />);
    snapshot([teammate, intruder]);
    expect(column(NAIVE).getByText("2")).toBeInTheDocument();
    expect(column(NAIVE).getByText("2 in a zone now")).toBeInTheDocument();
    expect(column(PIDS).getByText("1")).toBeInTheDocument();
    expect(column(PIDS).getByText("1 alerting now")).toBeInTheDocument();
    expect(screen.getByText(/50% fewer alarms than the naive geofence/)).toBeInTheDocument();
    expect(screen.queryByText("Awaiting data")).not.toBeInTheDocument();
  });

  it("keeps session totals after contacts leave", () => {
    render(<BaselinePanel />);
    snapshot([teammate, intruder]);
    snapshot([], "2026-10-27T04:30:05Z");
    expect(column(NAIVE).getByText("2")).toBeInTheDocument();
    expect(column(NAIVE).getByText("0 in a zone now")).toBeInTheDocument();
    expect(column(PIDS).getByText("1")).toBeInTheDocument();
    expect(column(PIDS).getByText("0 alerting now")).toBeInTheDocument();
  });

  it("resets the session totals on request", () => {
    render(<BaselinePanel />);
    snapshot([teammate, intruder]);
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(column(NAIVE).getByText("0")).toBeInTheDocument();
    expect(column(PIDS).getByText("0")).toBeInTheDocument();
    // contacts still on the floor are counted again from the next snapshot
    snapshot([intruder], "2026-10-27T04:31:00Z");
    expect(column(NAIVE).getByText("1")).toBeInTheDocument();
    expect(column(PIDS).getByText("1")).toBeInTheDocument();
  });
});
