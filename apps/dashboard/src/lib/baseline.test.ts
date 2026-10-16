import { describe, expect, it } from "vitest";

import { assessment } from "../test/fixtures";
import { accumulate, countNow, emptyTally, isNaiveAlarm, isPidsAlarm, verdict } from "./baseline";

describe("isNaiveAlarm", () => {
  it("alarms on anyone inside a zone, whatever PIDS rated them", () => {
    for (const level of ["nominal", "elevated", "warning", "critical"] as const) {
      expect(isNaiveAlarm(assessment({ level }))).toBe(true);
    }
  });

  it("stays quiet outside every zone, even for a PIDS alert", () => {
    expect(isNaiveAlarm(assessment({ zone_id: null, zone_kind: null, level: "warning" }))).toBe(
      false,
    );
  });

  it("alarms on a badged person the camera sees: it cannot tie a badge to a track", () => {
    const badged = assessment({ level: "nominal", tag_id: "badge-7", authorized: true });
    expect(isNaiveAlarm(badged)).toBe(true);
  });

  it("whitelists an authorised GPS device no camera sees, like the evaluation baseline", () => {
    const gps = { sources: ["gps:patrol-alpha"], tag_id: "patrol-alpha" };
    expect(isNaiveAlarm(assessment({ ...gps, authorized: true }))).toBe(false);
    expect(isNaiveAlarm(assessment({ ...gps, authorized: false }))).toBe(true);
  });
});

describe("isPidsAlarm", () => {
  it("counts WARNING and above, which is when PIDS raises an alert", () => {
    expect(isPidsAlarm(assessment({ level: "nominal" }))).toBe(false);
    expect(isPidsAlarm(assessment({ level: "elevated" }))).toBe(false);
    expect(isPidsAlarm(assessment({ level: "warning" }))).toBe(true);
    expect(isPidsAlarm(assessment({ level: "critical", zone_id: null }))).toBe(true);
  });
});

// The demo: a badged teammate and an un-badged intruder walk into the watched room.
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
const outside = assessment({ entity_id: "edge-01/a-3", zone_id: null, level: "nominal" });

describe("countNow", () => {
  it("counts the current contacts each system alarms on", () => {
    expect(countNow([teammate, intruder, outside])).toEqual({ naive: 2, pids: 1 });
    expect(countNow([])).toEqual({ naive: 0, pids: 0 });
  });
});

describe("accumulate", () => {
  it("counts each contact once and keeps those that have left", () => {
    let t = accumulate(emptyTally, [teammate, outside], "2026-10-27T04:30:00Z");
    t = accumulate(t, [teammate, intruder], "2026-10-27T04:30:01Z");
    t = accumulate(t, [], "2026-10-27T04:30:02Z");
    expect(Object.keys(t.naive).sort()).toEqual(["edge-01/a-1", "edge-01/a-2"]);
    expect(Object.keys(t.pids)).toEqual(["edge-01/a-2"]);
  });

  it("starts the clock at the first snapshot, even an empty one", () => {
    let t = accumulate(emptyTally, [], "2026-10-27T04:30:00Z");
    t = accumulate(t, [intruder], "2026-10-27T04:31:00Z");
    expect(t.startedAt).toBe("2026-10-27T04:30:00Z");
  });

  it("returns the same tally when nothing new happened", () => {
    const t = accumulate(emptyTally, [teammate, intruder], "2026-10-27T04:30:00Z");
    expect(accumulate(t, [intruder, outside], "2026-10-27T04:30:01Z")).toBe(t);
  });
});

describe("verdict", () => {
  it("states the reduction against the naive geofence", () => {
    expect(verdict({ naive: 2, pids: 1 })).toBe("50% fewer alarms than the naive geofence");
    expect(verdict({ naive: 3, pids: 3 })).toBe("As many alarms as the naive geofence");
    expect(verdict({ naive: 2, pids: 3 })).toBe("50% more alarms than the naive geofence");
  });

  it("handles a session with no zone entries", () => {
    expect(verdict({ naive: 0, pids: 0 })).toBe("No zone entries yet");
    expect(verdict({ naive: 0, pids: 1 })).toBe("PIDS alerted before any zone entry");
  });
});
