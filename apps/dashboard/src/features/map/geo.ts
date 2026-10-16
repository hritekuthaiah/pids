import type { ThreatAssessment } from "@pids/api-client";

const M_PER_DEG_LAT = 111_320;

/** Offset a lon/lat by metres east/north (local tangent plane; fine at site scale). */
export function offsetMetres(
  lon: number,
  lat: number,
  east: number,
  north: number,
): [number, number] {
  const mPerDegLon = M_PER_DEG_LAT * Math.cos((lat * Math.PI) / 180);
  return [lon + east / mPerDegLon, lat + north / M_PER_DEG_LAT];
}

/** Where a constant-velocity entity crosses into the core, if a breach is forecast. */
export function predictedBreachPoint(a: ThreatAssessment): [number, number] | null {
  const ttb = a.time_to_breach_s;
  if (ttb === null || !a.velocity) return null;
  return offsetMetres(
    a.position.lon,
    a.position.lat,
    a.velocity.east * ttb,
    a.velocity.north * ttb,
  );
}

/** Compass heading in degrees (clockwise from north) of a velocity, or null if ~stationary. */
export function headingDeg(a: ThreatAssessment): number | null {
  if (!a.velocity) return null;
  const { east, north } = a.velocity;
  if (Math.hypot(east, north) < 0.3) return null;
  return ((Math.atan2(east, north) * 180) / Math.PI + 360) % 360;
}

export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/** Bounding box of every coordinate in a polygon feature collection. */
export function bounds(fc: GeoJSON.FeatureCollection): [[number, number], [number, number]] {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const f of fc.features) {
    if (f.geometry.type !== "Polygon") continue;
    for (const ring of f.geometry.coordinates) {
      for (const [x, y] of ring) {
        if (x === undefined || y === undefined) continue;
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
        maxX = Math.max(maxX, x);
        maxY = Math.max(maxY, y);
      }
    }
  }
  return [
    [minX, minY],
    [maxX, maxY],
  ];
}
