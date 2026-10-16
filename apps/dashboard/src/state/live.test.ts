import { describe, expect, it } from "vitest";

import { alert, assessment } from "../test/fixtures";
import { TRAIL_POINTS, emptyLive, reduce, sortAlerts, unackedCritical } from "./live";

describe("reduce", () => {
  it("replaces the entity set on each live snapshot and grows trails", () => {
    let s = reduce(
      emptyLive,
      { type: "live", site_id: "s", at: "t1", entities: [assessment()] },
      1000,
    );
    s = reduce(
      s,
      {
        type: "live",
        site_id: "s",
        at: "t2",
        entities: [assessment({ position: { lat: 13.2629, lon: 77.42 } })],
      },
      2000,
    );
    expect(Object.keys(s.entities)).toEqual(["edge-01/123-7"]);
    expect(s.trails["edge-01/123-7"]).toHaveLength(2);
    expect(s.receivedAt).toBe(2000);
    expect(s.serverAt).toBe("t2");
  });

  it("drops entities that left and caps trail length", () => {
    let s = emptyLive;
    for (let i = 0; i < TRAIL_POINTS + 10; i++) {
      s = reduce(s, { type: "live", site_id: "s", at: `${i}`, entities: [assessment()] });
    }
    expect(s.trails["edge-01/123-7"]).toHaveLength(TRAIL_POINTS);
    s = reduce(s, { type: "live", site_id: "s", at: "x", entities: [] });
    expect(s.entities).toEqual({});
    expect(s.trails).toEqual({});
  });

  it("keeps active alerts and removes closed ones", () => {
    let s = reduce(emptyLive, {
      type: "alerts_snapshot",
      alerts: [alert("a", "warning"), alert("b", "critical")],
    });
    expect(Object.keys(s.alerts).sort()).toEqual(["a", "b"]);
    s = reduce(s, {
      type: "alert",
      event: "acknowledged",
      alert: alert("a", "warning", { status: "acknowledged" }),
    });
    expect(s.alerts["a"]?.status).toBe("acknowledged");
    s = reduce(s, {
      type: "alert",
      event: "false_alarm",
      alert: alert("b", "critical", { status: "false_alarm" }),
    });
    expect(Object.keys(s.alerts)).toEqual(["a"]);
  });
});

describe("alert ordering", () => {
  it("puts unacknowledged first, then severity, then newest", () => {
    const alerts = {
      old: alert("old", "critical", { opened_at: "2026-10-27T04:00:00Z" }),
      ack: alert("ack", "critical", { status: "acknowledged", opened_at: "2026-10-27T05:00:00Z" }),
      warn: alert("warn", "warning", { opened_at: "2026-10-27T05:00:00Z" }),
      fresh: alert("fresh", "critical", { opened_at: "2026-10-27T04:50:00Z" }),
    };
    expect(sortAlerts(alerts).map((a) => a.id)).toEqual(["fresh", "old", "warn", "ack"]);
  });

  it("selects only open critical alerts for the alarm", () => {
    const alerts = {
      a: alert("a", "critical"),
      b: alert("b", "critical", { status: "acknowledged" }),
      c: alert("c", "warning"),
    };
    expect(unackedCritical(alerts).map((a) => a.id)).toEqual(["a"]);
  });
});
