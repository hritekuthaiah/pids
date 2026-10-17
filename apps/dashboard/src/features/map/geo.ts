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

/**
 * Metres in one degree of latitude and of longitude at a latitude (WGS84 series), good
 * to about a millimetre across a site. `offsetMetres` above is the quick spherical
 * version for drawing; relocation needs this one so a room stays the size it was.
 */
export function metresPerDegree(lat: number): { lat: number; lon: number } {
  const p = (lat * Math.PI) / 180;
  return {
    lat: 111_132.92 - 559.82 * Math.cos(2 * p) + 1.175 * Math.cos(4 * p) - 0.0023 * Math.cos(6 * p),
    lon: 111_412.84 * Math.cos(p) - 93.5 * Math.cos(3 * p) + 0.118 * Math.cos(5 * p),
  };
}

/**
 * Carry a ring from one site origin to another, keeping its shape and size in metres:
 * each corner's east/north offset from `from` is laid down again from `to`. Used when
 * the whole site is relocated, so zones stay the size they were drawn at.
 */
export function translateRing(
  ring: [number, number][],
  from: { lat: number; lon: number },
  to: { lat: number; lon: number },
): [number, number][] {
  const a = metresPerDegree(from.lat);
  const b = metresPerDegree(to.lat);
  return ring.map(([lon, lat]) => [
    to.lon + ((lon - from.lon) * a.lon) / b.lon,
    to.lat + ((lat - from.lat) * a.lat) / b.lat,
  ]);
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
