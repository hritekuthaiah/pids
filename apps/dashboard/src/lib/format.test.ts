import { describe, expect, it } from "vitest";

import { clock, entityLabel, humanize, since } from "./format";

describe("format", () => {
  const t0 = new Date("2026-10-27T04:30:00Z").getTime();

  it.each([
    [5, "5s"],
    [65, "1m 05s"],
    [3725, "1h 02m"],
  ])("since(%is) = %s", (seconds, expected) => {
    expect(since("2026-10-27T04:30:00Z", t0 + seconds * 1000)).toBe(expected);
  });

  it("never reports negative elapsed time", () => {
    expect(since("2026-10-27T04:30:00Z", t0 - 5000)).toBe("0s");
  });

  it("labels entities compactly", () => {
    expect(entityLabel("edge-01/48213-7")).toBe("edge-01 · 7");
    expect(entityLabel("tag/patrol-alpha")).toBe("patrol-alpha");
  });

  it("humanises zone ids", () => {
    expect(humanize("compound-critical")).toBe("compound critical");
    expect(humanize(null)).toBe("open ground");
  });

  it("formats clocks in the site's time zone", () => {
    expect(clock(new Date("2026-10-27T04:30:05Z"), "Asia/Kolkata")).toBe("10:00:05");
    expect(clock(new Date("2026-10-27T04:30:05Z"), "UTC")).toBe("04:30:05");
  });
});
