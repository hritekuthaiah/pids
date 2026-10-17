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

  describe("relocating the site", () => {
    const OLD = { lat: 13.262, lon: 77.42 };
    const NEW: LngLat = [77.5, 13.1];
    const loaded = (): EditorState =>
      initial([{ id: "room", name: "Room", kind: "critical", ring: SQUARE }], OLD);

    it("carries the zones to the new origin and keeps their size", () => {
      const before = areaM2(SQUARE);
      const s = run([{ t: "origin", at: NEW }], loaded());
      const ring = at(s.drafts, 0).ring;
      expect(at(ring, 0)[0]).toBeCloseTo(NEW[0], 9); // the first corner sat on the old origin
      expect(at(ring, 0)[1]).toBeCloseTo(NEW[1], 9);
      expect(areaM2(ring)).toBeCloseTo(before, 0);
      expect(s.origin).toEqual({ lat: 13.1, lon: 77.5 });
      expect(s.dirty).toBe(true);
    });

    it("measures a second move from where the first one put the site", () => {
      const s = run(
        [
          { t: "origin", at: NEW },
          { t: "origin", at: [OLD.lon, OLD.lat] },
        ],
        loaded(),
      );
      for (const [i, p] of SQUARE.entries()) {
        expect(at(at(s.drafts, 0).ring, i)[0]).toBeCloseTo(p[0], 7);
        expect(at(at(s.drafts, 0).ring, i)[1]).toBeCloseTo(p[1], 7);
      }
    });

    it("leaves the zones on the ground when only the frame is re-anchored", () => {
      const s = run(
        [
          { t: "carry", on: false },
          { t: "origin", at: NEW },
        ],
        loaded(),
      );
      expect(at(s.drafts, 0).ring).toEqual(SQUARE);
      expect(s.origin).toEqual({ lat: 13.1, lon: 77.5 });
    });

    it("tells the server to relocate only for a carried move", () => {
      const moved = run([{ t: "origin", at: NEW }], loaded());
      expect(toPayload(moved, moved.origin ?? undefined)).toMatchObject({
        origin: { lat: 13.1, lon: 77.5 },
        relocate: true,
      });
      const reframed = run(
        [
          { t: "carry", on: false },
          { t: "origin", at: NEW },
        ],
        loaded(),
      );
      expect(toPayload(reframed, reframed.origin ?? undefined).relocate).toBe(false);
      expect(toPayload(loaded()).relocate).toBe(false); // zones edited, site not moved
      expect("origin" in toPayload(loaded())).toBe(false);
    });

    it("does not guess a relocation when the stored origin is unknown", () => {
      const s = run([{ t: "origin", at: NEW }], initial([]));
      expect(toPayload(s, s.origin ?? undefined).relocate).toBe(false);
    });

    it("abandons a half-drawn zone, which would otherwise be left behind", () => {
      const s = run(
        [
          { t: "draw", kind: "warning" },
          { t: "vertex", at: at(SQUARE, 0) },
          { t: "origin", at: NEW },
        ],
        loaded(),
      );
      expect(s.drawing).toBeNull();
    });
  });

  describe("typed coordinates", () => {
    it("moves one corner of any zone, selected or not", () => {
      const start = run(drawSquare("critical"));
      const s = run(
        [
          { t: "select", id: null },
          { t: "setVertex", id: "critical-core-1", index: 1, at: [77.43, 13.27] },
        ],
        start,
      );
      expect(at(at(s.drafts, 0).ring, 1)).toEqual([77.43, 13.27]);
      expect(at(s.drafts, 0).ring).toHaveLength(4);
    });

    it("adds a corner halfway to the next, wrapping round at the last one", () => {
      const start = run(drawSquare());
      const mid = run([{ t: "insertVertex", id: "warning-band-1", index: 0 }], start);
      expect(at(mid.drafts, 0).ring).toHaveLength(5);
      expect(at(at(mid.drafts, 0).ring, 1)[0]).toBeCloseTo(77.42005, 9);
      const wrap = run([{ t: "insertVertex", id: "warning-band-1", index: 3 }], start);
      expect(at(at(wrap.drafts, 0).ring, 4)).toEqual([77.42, 13.26205]);
    });

    it("keeps three corners when asked to remove one more", () => {
      const tri: LngLat[] = SQUARE.slice(0, 3);
      const s = run([
        { t: "addZone", kind: "warning", ring: tri },
        { t: "deleteVertex", index: 0 },
      ]);
      expect(at(s.drafts, 0).ring).toHaveLength(3);
    });

    it("adds a pasted zone, named and selected like a drawn one", () => {
      const s = run([{ t: "addZone", kind: "critical", ring: SQUARE }]);
      expect(at(s.drafts, 0)).toMatchObject({
        id: "critical-core-1",
        kind: "critical",
        ring: SQUARE,
      });
      expect(s.selected).toBe("critical-core-1");
      expect(s.dirty).toBe(true);
      expect(
        run([{ t: "addZone", kind: "critical", ring: SQUARE.slice(0, 2) }]).drafts,
      ).toHaveLength(0);
    });
  });
});
