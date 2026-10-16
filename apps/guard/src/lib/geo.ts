/** Distance and bearing from the guard to an alert — enough to set off in the right direction. */

const R = 6_371_000;
const rad = (d: number) => (d * Math.PI) / 180;

export interface LatLon {
  lat: number;
  lon: number;
}

export function distanceM(a: LatLon, b: LatLon): number {
  const dLat = rad(b.lat - a.lat);
  const dLon = rad(b.lon - a.lon);
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** Initial compass bearing a -> b, degrees in [0, 360). */
export function bearingDeg(a: LatLon, b: LatLon): number {
  const y = Math.sin(rad(b.lon - a.lon)) * Math.cos(rad(b.lat));
  const x =
    Math.cos(rad(a.lat)) * Math.sin(rad(b.lat)) -
    Math.sin(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.cos(rad(b.lon - a.lon));
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

const POINTS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"] as const;

export function compass(deg: number): (typeof POINTS)[number] {
  return POINTS[Math.round((((deg % 360) + 360) % 360) / 45) % 8] ?? "N";
}

/** "140 m NE", "1.2 km S" — what a guard reads at a glance. */
export function heading(from: LatLon, to: LatLon): string {
  const d = distanceM(from, to);
  const dist = d < 1000 ? `${String(Math.round(d))} m` : `${(d / 1000).toFixed(1)} km`;
  return `${dist} ${compass(bearingDeg(from, to))}`;
}

/** A geo: URI the phone's map app opens with a pin (no map SDK key needed). */
export function mapsUri(p: LatLon, label: string): string {
  const q = `${p.lat.toFixed(6)},${p.lon.toFixed(6)}`;
  return `geo:${q}?q=${q}(${encodeURIComponent(label)})`;
}
