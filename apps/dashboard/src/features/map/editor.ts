/**
 * Zone editing state: a small, pure reducer so the drawing rules are testable without
 * a map. The component below it only translates MapLibre events into these actions
 * and renders the result.
 *
 * Rings are WGS84 `[lon, lat]`, open (no repeated closing vertex) — the server closes
 * them when it converts to the site's local metres.
 */

import { translateRing } from "./geo";

export type ZoneKind = "warning" | "critical" | "containment";
export type LngLat = [number, number];
export interface Origin {
  lat: number;
  lon: number;
}

export interface Draft {
  id: string;
  name: string;
  kind: ZoneKind;
  ring: LngLat[];
}

export interface EditorState {
  drafts: Draft[];
  /** Vertices of the polygon being drawn, or null when not drawing. */
  drawing: LngLat[] | null;
  drawKind: ZoneKind;
  selected: string | null;
  dirty: boolean;
  /** True while the operator is picking a new site origin on the map. */
  placing: boolean;
  /** The origin they picked, in WGS84, or null to leave the site where it is. */
  origin: Origin | null;
  /** The site's origin as stored when editing began; null if unknown (tests, loading). */
  siteOrigin: Origin | null;
  /**
   * Whether picking a new origin moves the whole site, zones included (a relocation),
   * or only re-anchors the site's frame while the zones stay on the ground they cover.
   */
  carry: boolean;
}

export const KIND_LABEL: Record<ZoneKind, string> = {
  warning: "Warning band",
  critical: "Critical core",
  containment: "Containment",
};

/** The smallest polygon worth keeping: three distinct corners. */
export const MIN_VERTICES = 3;

export function initial(drafts: Draft[] = [], siteOrigin: Origin | null = null): EditorState {
  return {
    drafts,
    drawing: null,
    drawKind: "warning",
    selected: null,
    dirty: false,
    placing: false,
    origin: null,
    siteOrigin,
    carry: true,
  };
}

/** Where the site's frame is anchored right now: the picked origin, else the stored one. */
export function effectiveOrigin(state: EditorState): Origin | null {
  return state.origin ?? state.siteOrigin;
}

/** "Secure core" -> "secure-core"; ids must match the server's zone id pattern. */
export function slugify(name: string, taken: Iterable<string> = []): string {
  const base =
    name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 50) || "zone";
  const used = new Set(taken);
  if (!used.has(base)) return base;
  for (let n = 2; ; n += 1) {
    const candidate = `${base}-${String(n)}`;
    if (!used.has(candidate)) return candidate;
  }
}

export type Action =
  | { t: "load"; drafts: Draft[]; siteOrigin?: Origin | null }
  | { t: "draw"; kind: ZoneKind }
  | { t: "vertex"; at: LngLat }
  | { t: "undoVertex" }
  | { t: "finish" }
  | { t: "cancel" }
  | { t: "select"; id: string | null }
  | { t: "moveVertex"; index: number; at: LngLat }
  | { t: "deleteVertex"; index: number }
  | { t: "remove"; id: string }
  | { t: "rename"; id: string; name: string }
  | { t: "setKind"; id: string; kind: ZoneKind }
  | { t: "placeMode" }
  | { t: "origin"; at: LngLat }
  | { t: "carry"; on: boolean }
  | { t: "setVertex"; id: string; index: number; at: LngLat }
  | { t: "insertVertex"; id: string; index: number }
  | { t: "addZone"; kind: ZoneKind; ring: LngLat[] };

function patch(state: EditorState, id: string, f: (d: Draft) => Draft): EditorState {
  return {
    ...state,
    dirty: true,
    drafts: state.drafts.map((d) => (d.id === id ? f(d) : d)),
  };
}

export function reduce(state: EditorState, action: Action): EditorState {
  switch (action.t) {
    case "load":
      return initial(action.drafts, action.siteOrigin ?? null);
    case "draw":
      return { ...state, drawing: [], drawKind: action.kind, selected: null, placing: false };
    case "placeMode":
      return { ...state, placing: !state.placing, drawing: null };
    case "origin": {
      const to: Origin = { lat: action.at[1], lon: action.at[0] };
      const from = effectiveOrigin(state);
      const moved = state.carry && from !== null;
      return {
        ...state,
        placing: false,
        drawing: null,
        dirty: true,
        origin: to,
        drafts: moved
          ? state.drafts.map((d) => ({ ...d, ring: translateRing(d.ring, from, to) }))
          : state.drafts,
      };
    }
    case "carry":
      return { ...state, carry: action.on };
    case "setVertex":
      return patch(state, action.id, (d) => ({
        ...d,
        ring: d.ring.map((p, i) => (i === action.index ? action.at : p)),
      }));
    case "insertVertex":
      return patch(state, action.id, (d) => {
        const a = d.ring[action.index];
        const b = d.ring[(action.index + 1) % d.ring.length];
        if (!a || !b) return d;
        const mid: LngLat = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
        return {
          ...d,
          ring: [...d.ring.slice(0, action.index + 1), mid, ...d.ring.slice(action.index + 1)],
        };
      });
    case "addZone": {
      if (action.ring.length < MIN_VERTICES) return state;
      const n = state.drafts.filter((d) => d.kind === action.kind).length + 1;
      const id = slugify(
        `${KIND_LABEL[action.kind]} ${String(n)}`,
        state.drafts.map((d) => d.id),
      );
      return {
        ...state,
        drafts: [
          ...state.drafts,
          {
            id,
            name: `${KIND_LABEL[action.kind]} ${String(n)}`,
            kind: action.kind,
            ring: action.ring,
          },
        ],
        selected: id,
        drawing: null,
        dirty: true,
      };
    }
    case "vertex":
      return state.drawing ? { ...state, drawing: [...state.drawing, action.at] } : state;
    case "undoVertex":
      return state.drawing ? { ...state, drawing: state.drawing.slice(0, -1) } : state;
    case "finish": {
      if (!state.drawing || state.drawing.length < MIN_VERTICES) return state;
      const n = state.drafts.filter((d) => d.kind === state.drawKind).length + 1;
      const name = `${KIND_LABEL[state.drawKind]} ${String(n)}`;
      const id = slugify(
        name,
        state.drafts.map((d) => d.id),
      );
      return {
        ...state,
        drafts: [...state.drafts, { id, name, kind: state.drawKind, ring: state.drawing }],
        drawing: null,
        selected: id,
        dirty: true,
      };
    }
    case "cancel":
      return { ...state, drawing: null };
    case "select":
      return { ...state, selected: action.id, drawing: null };
    case "moveVertex": {
      const id = state.selected;
      if (id === null) return state;
      return patch(state, id, (d) => ({
        ...d,
        ring: d.ring.map((p, i) => (i === action.index ? action.at : p)),
      }));
    }
    case "deleteVertex": {
      const id = state.selected;
      const draft = state.drafts.find((d) => d.id === id);
      if (id === null || !draft || draft.ring.length <= MIN_VERTICES) return state;
      return patch(state, id, (d) => ({ ...d, ring: d.ring.filter((_, i) => i !== action.index) }));
    }
    case "remove":
      return {
        ...state,
        drafts: state.drafts.filter((d) => d.id !== action.id),
        selected: state.selected === action.id ? null : state.selected,
        dirty: true,
      };
    case "rename":
      return patch(state, action.id, (d) => ({ ...d, name: action.name }));
    case "setKind":
      return patch(state, action.id, (d) => ({ ...d, kind: action.kind }));
  }
}

/** What the map draws while editing: finished drafts plus the in-progress outline. */
export function toGeoJSON(state: EditorState): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = state.drafts.map((d) => ({
    type: "Feature",
    id: d.id,
    properties: { id: d.id, name: d.name, kind: d.kind, selected: d.id === state.selected },
    geometry: { type: "Polygon", coordinates: [closed(d.ring)] },
  }));
  const drawing = state.drawing;
  if (drawing && drawing.length > 0) {
    features.push({
      type: "Feature",
      properties: { id: "__drawing", kind: state.drawKind, drawing: true },
      geometry:
        drawing.length >= MIN_VERTICES
          ? { type: "Polygon", coordinates: [closed(drawing)] }
          : { type: "LineString", coordinates: drawing },
    });
  }
  return { type: "FeatureCollection", features };
}

/** Draggable handles for the selected zone, and the in-progress vertices. */
export function vertexGeoJSON(state: EditorState): GeoJSON.FeatureCollection {
  const ring = state.drawing ?? state.drafts.find((d) => d.id === state.selected)?.ring ?? [];
  return {
    type: "FeatureCollection",
    features: ring.map((p, i) => ({
      type: "Feature",
      properties: { index: i, pending: state.drawing !== null },
      geometry: { type: "Point", coordinates: p },
    })),
  };
}

function closed(ring: LngLat[]): LngLat[] {
  if (ring.length === 0) return ring;
  const [first] = ring;
  const last = ring[ring.length - 1];
  if (!first || !last) return ring;
  return first[0] === last[0] && first[1] === last[1] ? ring : [...ring, first];
}

/** Ground area in m², for the operator to sanity-check what they drew (spherical excess is negligible here). */
export function areaM2(ring: LngLat[]): number {
  if (ring.length < MIN_VERTICES) return 0;
  const lat0 = (ring.reduce((s, p) => s + p[1], 0) / ring.length) * (Math.PI / 180);
  const mx = 111_320 * Math.cos(lat0);
  const my = 110_574;
  let sum = 0;
  for (let i = 0; i < ring.length; i += 1) {
    const a = ring[i];
    const b = ring[(i + 1) % ring.length];
    if (!a || !b) continue;
    sum += a[0] * mx * (b[1] * my) - b[0] * mx * (a[1] * my);
  }
  return Math.abs(sum) / 2;
}

/**
 * The PUT body: zones as drawn, plus the origin when the operator moved the site. A
 * carried move is a relocation: the server then keeps cameras and readers at their place
 * in the site's frame so they travel with the zones.
 */
export function toPayload(state: EditorState, origin?: Origin) {
  return {
    ...(origin ? { origin } : {}),
    relocate: origin !== undefined && state.carry && state.siteOrigin !== null,
    zones: state.drafts.map((d) => ({
      id: d.id,
      name: d.name,
      kind: d.kind,
      ring: d.ring,
      actions: {},
    })),
  };
}

/** Pull the drafts back out of the site's GeoJSON so an edit starts from what is live. */
export function draftsFrom(geojson: GeoJSON.FeatureCollection): Draft[] {
  return geojson.features
    .filter((f) => f.properties?.["layer"] === "zone" && f.geometry.type === "Polygon")
    .map((f) => {
      const ring = (f.geometry as GeoJSON.Polygon).coordinates[0] ?? [];
      const open = ring.slice(0, Math.max(0, ring.length - 1)) as LngLat[];
      return {
        id: String(f.properties?.["id"] ?? ""),
        name: String(f.properties?.["name"] ?? ""),
        kind: String(f.properties?.["kind"] ?? "warning") as ZoneKind,
        ring: open,
      };
    });
}
