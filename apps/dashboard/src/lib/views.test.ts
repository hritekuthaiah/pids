import { describe, expect, it } from "vitest";

import { footprintGeoJSON, pixelToGround, previewPointToLngLat, type NodeView } from "./views";

/**
 * A camera 2.5 m up, looking north and 28 degrees down, at the demo-room origin. The
 * homography below is the one `pids_edge.ground.from_pose` produces for that pose, so
 * these are the numbers the console really receives.
 */
const VIEW: NodeView = {
  schema_version: 1,
  site_id: "demo-room",
  node_id: "edge-01",
  at: "2026-10-27T10:00:00Z",
  image_size: [1280, 720],
  // pixels -> metres east/north, row major: exactly what pids_edge.ground.from_pose
  // produces for this pose, so these are the numbers the console really receives.
  homography: [
    [0.022473367, -0.0, -14.382954926],
    [-0.0, -0.010550607, 21.934834705],
    [0.0, 0.007937122, 1.0],
  ],
  footprint: [
    { lat: 13.262, lon: 77.42 },
    { lat: 13.2621, lon: 77.42 },
    { lat: 13.2621, lon: 77.4201 },
  ],
  origin: { lat: 13.262, lon: 77.42 },
  calibration_method: "aruco",
  calibration_rms_m: 0.02,
};

describe("camera views", () => {
  it("projects a pixel onto the ground", () => {
    const bottomCentre = pixelToGround(VIEW, 640, 719);
    expect(bottomCentre).not.toBeNull();
    const [east, north] = bottomCentre ?? [0, 0];
    expect(east).toBeCloseTo(0, 1); // straight ahead
    expect(north).toBeCloseTo(2.14, 1); // 2.5 m up, pitched 28 deg down
    const [, far] = pixelToGround(VIEW, 640, 0) ?? [0, 0];
    expect(far).toBeGreaterThan(north); // the top of the frame is further away
  });

  it("refuses pixels beyond the horizon", () => {
    // this camera's horizon sits ~126 px above the frame; past it the projection
    // flips sign and would place a point behind the lens
    expect(pixelToGround(VIEW, 640, -200)).toBeNull();
  });

  it("turns a click on the preview into a map position", () => {
    const near = previewPointToLngLat(VIEW, 0.5, 0.99);
    const far = previewPointToLngLat(VIEW, 0.5, 0.05);
    expect(near?.north).toBeCloseTo(2.17, 1);
    expect(near?.lngLat[1]).toBeGreaterThan(VIEW.origin.lat); // north of the origin
    expect(near?.lngLat[0]).toBeCloseTo(VIEW.origin.lon, 5);
    // further up the image is further away on the ground
    expect(far?.north ?? 0).toBeGreaterThan(near?.north ?? 0);
  });

  it("closes each footprint ring and skips degenerate ones", () => {
    const fc = footprintGeoJSON([VIEW, { ...VIEW, node_id: "edge-02", footprint: [] }]);
    expect(fc.features).toHaveLength(1);
    const ring = (fc.features[0]?.geometry as GeoJSON.Polygon).coordinates[0] ?? [];
    expect(ring).toHaveLength(4);
    expect(ring[0]).toEqual(ring[3]);
  });
});
