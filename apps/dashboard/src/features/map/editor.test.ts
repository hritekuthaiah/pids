import { describe, expect, it } from "vitest";

import {
  areaM2,
  draftsFrom,
  initial,
  reduce,
  slugify,
  toGeoJSON,
  toPayload,
  vertexGeoJSON,
  type Action,
  type EditorState,
  type LngLat,
} from "./editor";

const SQUARE: LngLat[] = [
  [77.42, 13.262],
  [77.4201, 13.262],
  [77.4201, 13.2621],
  [77.42, 13.2621],
];

/** Indexing with `noUncheckedIndexedAccess` on: fail loudly instead of asserting non-null. */
function at<T>(xs: readonly T[], i: number): T {
  const value = xs[i];
  if (value === undefined) throw new Error(`no element ${String(i)}`);
  return value;
}

const run = (actions: Action[], from: EditorState = initial()): EditorState =>
  actions.reduce(reduce, from);

const drawSquare = (kind: "warning" | "critical" | "containment" = "warning"): Action[] => [
  { t: "draw", kind },
  ...SQUARE.map((at): Action => ({ t: "vertex", at })),
  { t: "finish" },
];

describe("zone editor", () => {
  it("draws a polygon and names it after its kind", () => {
    const s = run(drawSquare("critical"));
    expect(s.drafts).toHaveLength(1);
    expect(s.drafts[0]).toMatchObject({ id: "critical-core-1", kind: "critical", ring: SQUARE });
    expect(s.selected).toBe("critical-core-1");
    expect(s.drawing).toBeNull();
    expect(s.dirty).toBe(true);
  });

  it("needs three corners before it will close", () => {
    const s = run([
      { t: "draw", kind: "warning" },
      { t: "vertex", at: at(SQUARE, 0) },
      { t: "vertex", at: at(SQUARE, 1) },
      { t: "finish" },
    ]);
    expect(s.drafts).toHaveLength(0);
    expect(s.drawing).toHaveLength(2); // still drawing
  });

  it("undoes a corner and cancels a drawing without touching saved zones", () => {
    const after = run([
      ...drawSquare(),
      { t: "draw", kind: "warning" },
      { t: "vertex", at: at(SQUARE, 0) },
      { t: "undoVertex" },
      { t: "cancel" },
    ]);
    expect(after.drawing).toBeNull();
    expect(after.drafts).toHaveLength(1);
  });

  it("moves and deletes vertices of the selected zone, keeping a triangle minimum", () => {
    const moved = run([...drawSquare(), { t: "moveVertex", index: 1, at: [77.4205, 13.2625] }]);
    expect(at(moved.drafts, 0).ring[1]).toEqual([77.4205, 13.2625]);
    const trimmed = reduce(moved, { t: "deleteVertex", index: 0 });
    expect(at(trimmed.drafts, 0).ring).toHaveLength(3);
    expect(at(reduce(trimmed, { t: "deleteVertex", index: 0 }).drafts, 0).ring).toHaveLength(3);
  });

  it("renames, retypes and removes zones", () => {
    let s = run(drawSquare());
    s = reduce(s, { t: "rename", id: "warning-band-1", name: "North field" });
    s = reduce(s, { t: "setKind", id: "warning-band-1", kind: "containment" });
    expect(s.drafts[0]).toMatchObject({ name: "North field", kind: "containment" });
    s = reduce(s, { t: "remove", id: "warning-band-1" });
    expect(s.drafts).toHaveLength(0);
    expect(s.selected).toBeNull();
  });

  it("gives every zone a unique id", () => {
    const s = run([...drawSquare(), ...drawSquare()]);
    expect(s.drafts.map((d) => d.id)).toEqual(["warning-band-1", "warning-band-2"]);
    expect(slugify("Secure core", ["secure-core"])).toBe("secure-core-2");
    expect(slugify("!!!")).toBe("zone");
  });

  it("places a new origin and marks the edit dirty", () => {
    const s = run([{ t: "placeMode" }, { t: "origin", at: [77.5, 13.3] }]);
    expect(s.placing).toBe(false);
    expect(s.origin).toEqual({ lat: 13.3, lon: 77.5 });
    expect(toPayload(s, s.origin ?? undefined).origin).toEqual({ lat: 13.3, lon: 77.5 });
  });

  it("renders closed polygons, an open line while drawing, and vertex handles", () => {
    const s = run([
      ...drawSquare(),
      { t: "draw", kind: "critical" },
      { t: "vertex", at: at(SQUARE, 0) },
    ]);
    const fc = toGeoJSON(s);
    const polygon = at(fc.features, 0).geometry as GeoJSON.Polygon;
    expect(polygon.coordinates[0]).toHaveLength(5); // closed
    expect(at(polygon.coordinates, 0).at(-1)).toEqual(SQUARE[0]);
    expect(at(fc.features, 1).geometry.type).toBe("LineString"); // one corner so far
    expect(vertexGeoJSON(s).features).toHaveLength(1); // handles follow the drawing
  });

  it("round-trips the site's zones so an edit starts from what is live", () => {
    const site: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: { layer: "zone", id: "secure-core", name: "Secure Core", kind: "critical" },
          geometry: { type: "Polygon", coordinates: [[...SQUARE, at(SQUARE, 0)]] },
        },
        {
          type: "Feature",
          properties: { layer: "node", id: "edge-01" },
          geometry: { type: "Point", coordinates: at(SQUARE, 0) },
        },
      ],
    };
    const drafts = draftsFrom(site);
    expect(drafts).toHaveLength(1); // nodes are not zones
    expect(drafts[0]).toMatchObject({ id: "secure-core", kind: "critical" });
    expect(at(drafts, 0).ring).toHaveLength(4); // the closing vertex is dropped
    expect(at(toPayload(initial(drafts)).zones, 0).ring).toEqual(SQUARE);
  });

  it("measures ground area", () => {
    // ~0.0001 deg lon x 0.0001 deg lat at 13 N is about 10.8 m x 11.1 m
    expect(areaM2(SQUARE)).toBeGreaterThan(100);
    expect(areaM2(SQUARE)).toBeLessThan(140);
    expect(areaM2(SQUARE.slice(0, 2))).toBe(0);
  });
});
