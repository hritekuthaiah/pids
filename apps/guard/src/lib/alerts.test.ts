import type { Alert, AlertMessage } from "@pids/api-client";
import { describe, expect, it } from "vitest";

import { ago, headline, instruction, shouldNotify, sortAlerts } from "./alerts";

const base = {
  site_id: "demo-room",
  entity_id: "edge-01/1",
  score: 60,
  zone_id: "secure-core",
  entity_class: "person",
  tag_id: null,
  reason: "Unidentified person inside the secure core",
  lat: 13.262,
  lon: 77.42,
  updated_at: "2026-10-27T10:00:00Z",
  cleared_at: null,
  track_lost: false,
} as const;

const alert = (id: string, level: string, status: string, openedAt: string): Alert =>
  ({ ...base, id, level, max_level: level, status, opened_at: openedAt }) as unknown as Alert;

describe("alerts", () => {
  it("orders active, severe and recent first", () => {
    const sorted = sortAlerts([
      alert("a", "warning", "open", "2026-10-27T10:00:00Z"),
      alert("b", "critical", "resolved", "2026-10-27T10:05:00Z"),
      alert("c", "critical", "acknowledged", "2026-10-27T09:00:00Z"),
      alert("d", "warning", "open", "2026-10-27T10:01:00Z"),
    ]);
    expect(sorted.map((a) => a.id)).toEqual(["c", "d", "a", "b"]);
  });

  it("buzzes only for raises and escalations at warning or above", () => {
    const msg = (event: string, level: string) =>
      ({
        type: "alert",
        event,
        alert: alert("x", level, "open", base.updated_at),
      }) as unknown as AlertMessage;
    expect(shouldNotify(msg("raised", "warning"))).toBe(true);
    expect(shouldNotify(msg("escalated", "critical"))).toBe(true);
    expect(shouldNotify(msg("raised", "elevated"))).toBe(false);
    expect(shouldNotify(msg("cleared", "critical"))).toBe(false);
    expect(shouldNotify(msg("acknowledged", "critical"))).toBe(false);
  });

  it("says who, where and what to do", () => {
    expect(headline(alert("x", "critical", "open", base.updated_at))).toBe("Person · secure core");
    expect(instruction("critical", false)).toMatch(/do not engage alone/);
    expect(instruction("warning", true)).toMatch(/last known position/);
  });

  it("formats age", () => {
    const now = Date.parse("2026-10-27T10:00:00Z");
    expect(ago("2026-10-27T09:59:15Z", now)).toBe("45s ago");
    expect(ago("2026-10-27T08:30:00Z", now)).toBe("1h 30m ago");
  });
});
