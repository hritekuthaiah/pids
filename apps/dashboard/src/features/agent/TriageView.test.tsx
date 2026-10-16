import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Triage } from "../../lib/agent";
import { TriageView } from "./TriageView";

const report: Triage = {
  id: "00000000-0000-0000-0000-000000000001",
  alert_id: "demo-room@x/edge-01/1/1",
  provider: "anthropic",
  model: "claude-opus-5-5",
  created_at: "2026-10-27T10:00:00Z",
  latency_ms: 8400,
  summary: "An untagged person entered the secure core.",
  verdict: "likely_intrusion",
  confidence: 0.86,
  likely_cause: "Unauthorised entry.",
  recommended_actions: [
    {
      action: "Dispatch the nearest guard.",
      priority: "now",
      rationale: "Core breach.",
      procedure_ref: "sop-01-intrusion-response#1",
      decision: null,
      decided_at: null,
    },
    {
      action: "Close the vehicle gate.",
      priority: "soon",
      rationale: "Contain.",
      procedure_ref: "",
      decision: "approved",
      decided_at: "2026-10-27T10:01:00Z",
    },
  ],
  cited_procedures: ["sop-01-intrusion-response#1"],
  incident_report: "At 10:00 an untagged person ...",
  tool_calls: ["get_alert", "search_procedures"],
};

describe("TriageView", () => {
  it("shows the verdict, actions and citations, and asks for per-action decisions", async () => {
    const onDecide = vi.fn();
    render(<TriageView report={report} onDecide={onDecide} />);
    expect(screen.getByText("Likely intrusion")).toBeInTheDocument();
    expect(screen.getByText("confidence 86%")).toBeInTheDocument();
    expect(screen.getAllByText("SOP-01 §1").length).toBeGreaterThan(0);
    expect(screen.getByText("approved")).toBeInTheDocument();
    expect(screen.getByText(/verify before acting/)).toBeInTheDocument();
    // only the undecided action offers buttons
    const approve = screen.getAllByRole("button", { name: "Approve" });
    expect(approve).toHaveLength(1);
    await userEvent.click(approve[0] as HTMLElement);
    expect(onDecide).toHaveBeenCalledWith(0, "approved");
  });

  it("reveals the incident report draft on demand", async () => {
    render(<TriageView report={report} onDecide={() => undefined} />);
    expect(screen.queryByText(/At 10:00/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Incident report draft" }));
    expect(screen.getByText(/At 10:00/)).toBeInTheDocument();
  });
});
