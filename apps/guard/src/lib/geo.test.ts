import { describe, expect, it } from "vitest";

import { bearingDeg, compass, distanceM, heading, mapsUri } from "./geo";

const svit = { lat: 13.262, lon: 77.42 };

describe("geo", () => {
  it("measures short distances like a tape", () => {
    const north100 = { lat: svit.lat + 100 / 111_195, lon: svit.lon };
    expect(distanceM(svit, north100)).toBeCloseTo(100, 0);
  });

  it("gives compass bearings", () => {
    expect(bearingDeg(svit, { lat: svit.lat + 0.001, lon: svit.lon })).toBeCloseTo(0, 3);
    expect(bearingDeg(svit, { lat: svit.lat, lon: svit.lon + 0.001 })).toBeCloseTo(90, 1);
    expect(compass(44)).toBe("NE");
    expect(compass(359)).toBe("N");
    expect(compass(-90)).toBe("W");
  });

  it("reads at a glance", () => {
    expect(heading(svit, { lat: svit.lat - 0.0012, lon: svit.lon + 0.0012 })).toMatch(
      /^1\d\d m SE$/,
    );
    expect(heading(svit, { lat: svit.lat + 0.02, lon: svit.lon })).toBe("2.2 km N");
  });

  it("builds a geo: URI with a labelled pin", () => {
    expect(mapsUri(svit, "Secure core")).toBe(
      "geo:13.262000,77.420000?q=13.262000,77.420000(Secure%20core)",
    );
  });
});
