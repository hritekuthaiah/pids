import { describe, expect, it } from "vitest";

import { filterChips, procedureLabel } from "./agent";

describe("agent helpers", () => {
  it("labels procedure sections compactly", () => {
    expect(procedureLabel("sop-01-intrusion-response#2")).toBe("SOP-01 §2");
    expect(procedureLabel("something-else")).toBe("something-else");
  });

  it("shows the interpreted filter as chips", () => {
    expect(
      filterChips({
        since_minutes: 1440,
        levels: ["critical", "warning"],
        zone_ids: ["secure-core"],
        entity_classes: [],
        statuses: [],
        tag_id: "",
        track_lost_only: true,
      }),
    ).toEqual(["last 1d", "critical | warning", "secure-core", "lost tracks"]);
    expect(filterChips({ since_minutes: 90 })[0]).toBe("last 90m");
    expect(filterChips({ since_minutes: 120 })[0]).toBe("last 2h");
  });
});
