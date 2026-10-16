import { describe, expect, it } from "vitest";

import { assessment } from "../../test/fixtures";
import { bounds, headingDeg, offsetMetres, predictedBreachPoint } from "./geo";

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
});
