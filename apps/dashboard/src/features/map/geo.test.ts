import { describe, expect, it } from "vitest";

import { assessment } from "../../test/fixtures";
import {
  bounds,
  headingDeg,
  metresPerDegree,
  offsetMetres,
  predictedBreachPoint,
  translateRing,
} from "./geo";

describe("map geometry", () => {
  it("offsets ~111 km per degree of latitude", () => {
    const [lon, lat] = offsetMetres(77.42, 13.262, 0, 111.32);
    expect(lon).toBeCloseTo(77.42, 9);
    expect(lat).toBeCloseTo(13.263, 6);
  });

  it("projects the breach point along the velocity", () => {
    const end = predictedBreachPoint(
      assessment({ velocity: { east: 0, north: -2 }, time_to_breach_s: 10 }),
    );
    expect(end).not.toBeNull();
    const [, lat] = end ?? [0, 0];
    expect(lat).toBeCloseTo(13.263 - 20 / 111_320, 7);
  });

  it("has no breach point without a forecast", () => {
    expect(predictedBreachPoint(assessment({ time_to_breach_s: null }))).toBeNull();
  });

  it.each([
    [{ east: 0, north: 1 }, 0],
    [{ east: 1, north: 0 }, 90],
    [{ east: 0, north: -1 }, 180],
    [{ east: -1, north: 0 }, 270],
  ])("heading of %o is %i°", (velocity, expected) => {
    expect(headingDeg(assessment({ velocity }))).toBeCloseTo(expected);
  });

  it("treats a near-stationary entity as having no heading", () => {
    expect(headingDeg(assessment({ velocity: { east: 0.1, north: 0.1 } }))).toBeNull();
  });

  it("bounds polygons only", () => {
    const fc: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: {},
          geometry: {
            type: "Polygon",
            coordinates: [
              [
                [1, 2],
                [3, 2],
                [3, 5],
                [1, 2],
              ],
            ],
          },
        },
        { type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [100, 100] } },
      ],
    };
    expect(bounds(fc)).toEqual([
      [1, 2],
      [3, 5],
    ]);
  });

  it("knows how long a degree is", () => {
    // reference values for the WGS84 ellipsoid
    expect(metresPerDegree(0).lat).toBeCloseTo(110_574, -1);
    expect(metresPerDegree(13.262).lat).toBeCloseTo(110_633, -1);
    expect(metresPerDegree(13.262).lon).toBeCloseTo(108_366, -1);
    expect(metresPerDegree(45).lon).toBeCloseTo(78_847, -1);
  });

  it("carries a ring to a new origin without changing its size", () => {
    const from = { lat: 13.262, lon: 77.42 };
    const to = { lat: 28.6139, lon: 77.209 }; // a different latitude: degrees of longitude shrink
    const at = metresPerDegree(from.lat);
    const room: [number, number][] = [
      [from.lon, from.lat],
      [from.lon + 8 / at.lon, from.lat],
      [from.lon + 8 / at.lon, from.lat + 6 / at.lat],
      [from.lon, from.lat + 6 / at.lat],
    ];
    const moved = translateRing(room, from, to);
    expect(moved[0]?.[0]).toBeCloseTo(to.lon, 9);
    expect(moved[0]?.[1]).toBeCloseTo(to.lat, 9);
    // still 8 m east and 6 m north of the origin, measured in the new place
    const there = metresPerDegree(to.lat);
    expect(((moved[2]?.[0] ?? 0) - to.lon) * there.lon).toBeCloseTo(8, 6);
    expect(((moved[2]?.[1] ?? 0) - to.lat) * there.lat).toBeCloseTo(6, 6);
  });

  it("is undone by carrying it back", () => {
    const a = { lat: 13.262, lon: 77.42 };
    const b = { lat: 13.1, lon: 77.5 };
    const ring: [number, number][] = [
      [77.42, 13.262],
      [77.4201, 13.262],
      [77.4201, 13.2621],
    ];
    const back = translateRing(translateRing(ring, a, b), b, a);
    for (const [i, p] of ring.entries()) {
      expect(back[i]?.[0]).toBeCloseTo(p[0], 7);
      expect(back[i]?.[1]).toBeCloseTo(p[1], 7);
    }
  });
});
