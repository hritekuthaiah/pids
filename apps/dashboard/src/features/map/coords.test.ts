import { describe, expect, it } from "vitest";

import { formatCoordinate, parseCorners, parseLatitude, parseLongitude, parsePair } from "./coords";

describe("coordinate parsing", () => {
  it("reads decimal degrees, with a degree sign or a hemisphere letter", () => {
    expect(parseLatitude("13.262")).toBe(13.262);
    expect(parseLatitude(" 13.262° ")).toBe(13.262);
    expect(parseLatitude("13.262 S")).toBe(-13.262);
    expect(parseLongitude("77.42 w")).toBe(-77.42);
    expect(parseLongitude("-77.42")).toBe(-77.42);
    expect(parseLongitude(".5")).toBe(0.5);
  });

  it("refuses what is not a coordinate, or is off the globe", () => {
    for (const bad of ["", "abc", "13,262", "13.262 77.42", "91", "-90.0001"]) {
      expect(parseLatitude(bad), bad).toBeNull();
    }
    expect(parseLongitude("180.5")).toBeNull();
    expect(parseLatitude("90")).toBe(90);
  });

  it("reads a lat, lon pair the way map apps copy it", () => {
    const want = { lat: 13.262, lon: 77.42 };
    expect(parsePair("13.262000, 77.420000")).toEqual(want);
    expect(parsePair("(13.262, 77.42)")).toEqual(want);
    expect(parsePair("[13.262; 77.42]")).toEqual(want);
    expect(parsePair("13.262 77.42")).toEqual(want);
    expect(parsePair("  13.262N   77.42E ")).toEqual(want);
    expect(parsePair("-33.8688, 151.2093")).toEqual({ lat: -33.8688, lon: 151.2093 });
  });

  it("lets hemisphere letters put longitude first", () => {
    expect(parsePair("77.42E 13.262N")).toEqual({ lat: 13.262, lon: 77.42 });
    expect(parsePair("77.42 13.262N")).toEqual({ lat: 13.262, lon: 77.42 });
    expect(parsePair("13.262S, 77.42W")).toEqual({ lat: -13.262, lon: -77.42 });
  });

  it("refuses a pair with one number, junk, or a latitude past the pole", () => {
    for (const bad of ["13.262", "13.262,", "a, b", "95, 10", "13.2, 77.4, 5", ""]) {
      expect(parsePair(bad), bad).toBeNull();
    }
  });

  it("shows seven decimals, about a centimetre", () => {
    expect(formatCoordinate(13.262)).toBe("13.2620000");
    expect(formatCoordinate(77.4200000123)).toBe("77.4200000");
  });
});

describe("pasted corner lists", () => {
  const SURVEY = "13.262000, 77.420000\n13.262000, 77.420090\n13.262050, 77.420090\n";

  it("turns lines into a lon/lat ring", () => {
    const r = parseCorners(SURVEY);
    expect(r).toEqual({
      ok: true,
      ring: [
        [77.42, 13.262],
        [77.42009, 13.262],
        [77.42009, 13.26205],
      ],
    });
  });

  it("ignores blank lines and Windows line endings", () => {
    const r = parseCorners("\r\n13.262, 77.42\r\n\r\n13.262, 77.4201\r\n13.2621, 77.4201\r\n");
    expect(r.ok && r.ring).toHaveLength(3);
  });

  it("drops a repeated closing corner, because the server closes rings itself", () => {
    const r = parseCorners(`${SURVEY}13.262000, 77.420000`);
    expect(r.ok && r.ring).toHaveLength(3);
  });

  it("points at the line it could not read", () => {
    const r = parseCorners("13.262, 77.42\nnorth wall\n13.2, 77.4");
    expect(r).toEqual({
      ok: false,
      error: 'Line 2 is not "latitude, longitude": north wall',
    });
  });

  it("needs three corners", () => {
    for (const text of ["", "13.262, 77.42\n13.262, 77.4201"]) {
      const r = parseCorners(text);
      expect(r.ok).toBe(false);
    }
  });
});
