/**
 * Typing coordinates in: parsing for the origin fields and the "add a zone from
 * coordinates" box. Operators paste what a map app copies ("13.262000, 77.420000"),
 * so the parser is forgiving about separators, brackets, degree signs and hemisphere
 * letters, and strict about everything else: a wrong corner is a wrong zone.
 */
import type { LngLat } from "./editor";

export interface LatLon {
  lat: number;
  lon: number;
}

/** Decimal places kept when showing a coordinate: 1e-7° is about a centimetre. */
export const PRECISION = 7;

export function formatCoordinate(value: number): string {
  return value.toFixed(PRECISION);
}

const NUMBER = String.raw`[+-]?\d+(?:\.\d+)?|[+-]?\.\d+`;
const SINGLE = new RegExp(String.raw`^\s*(${NUMBER})\s*°?\s*([NSEWnsew])?\s*$`);

/** One decimal-degree value, optionally with a hemisphere letter (S and W are negative). */
function parseDegrees(text: string, max: number): number | null {
  const m = SINGLE.exec(text);
  if (!m) return null;
  let value = Number(m[1]);
  if (!Number.isFinite(value)) return null;
  const hemisphere = m[2]?.toUpperCase();
  if (hemisphere === "S" || hemisphere === "W") value = -Math.abs(value);
  if (Math.abs(value) > max) return null;
  return value;
}

export const parseLatitude = (text: string): number | null => parseDegrees(text, 90);
export const parseLongitude = (text: string): number | null => parseDegrees(text, 180);

const PAIR = new RegExp(
  String.raw`^[\s(\[]*(${NUMBER})\s*°?\s*([NSEWnsew])?\s*(?:,|;|\s)\s*(${NUMBER})\s*°?\s*([NSEWnsew])?[\s)\]]*$`,
);

/**
 * A "lat, lon" pair as map apps copy it. Letters may swap the order ("77.42E 13.26N"),
 * and without letters the first number is the latitude.
 */
export function parsePair(text: string): LatLon | null {
  const m = PAIR.exec(text);
  if (!m) return null;
  const [, a, ha, b, hb] = m;
  if (a === undefined || b === undefined) return null;
  const first = (ha ?? "").toUpperCase();
  const second = (hb ?? "").toUpperCase();
  const lonFirst = "EW".includes(first || "-") || "NS".includes(second || "-");
  const latText = lonFirst ? `${b}${second}` : `${a}${first}`;
  const lonText = lonFirst ? `${a}${first}` : `${b}${second}`;
  const lat = parseLatitude(latText);
  const lon = parseLongitude(lonText);
  return lat === null || lon === null ? null : { lat, lon };
}

export type CornerList = { ok: true; ring: LngLat[] } | { ok: false; error: string };

/**
 * One corner per line, "lat, lon". A repeated closing corner is dropped, because the
 * server closes rings itself; at least three distinct corners are needed.
 */
export function parseCorners(text: string): CornerList {
  const ring: LngLat[] = [];
  const lines = text.split(/\r?\n/);
  for (const [i, raw] of lines.entries()) {
    const line = raw.trim();
    if (line === "") continue;
    const pair = parsePair(line);
    if (!pair) {
      return { ok: false, error: `Line ${String(i + 1)} is not "latitude, longitude": ${line}` };
    }
    ring.push([pair.lon, pair.lat]);
  }
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (ring.length > 3 && first && last && first[0] === last[0] && first[1] === last[1]) {
    ring.pop();
  }
  if (ring.length < 3) {
    return { ok: false, error: "A zone needs at least three corners, one per line." };
  }
  return { ok: true, ring };
}
