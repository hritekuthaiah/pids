/**
 * MapLibre wiring for zone editing: turns pointer and key events into `editor.ts`
 * actions, and keeps two GeoJSON sources (shapes, vertex handles) in step with the
 * state. Everything that decides *what* an action means lives in the reducer.
 */
import type { Map as MapLibreMap, MapMouseEvent } from "maplibre-gl";
import { useCallback, useEffect, useReducer, useRef } from "react";

import { bounds } from "./geo";
import {
  MIN_VERTICES,
  initial,
  reduce,
  toGeoJSON,
  vertexGeoJSON,
  type Draft,
  type EditorState,
  type LngLat,
  type Origin,
  type ZoneKind,
} from "./editor";

const SHAPES = "editor-shapes";
const VERTICES = "editor-vertices";
const TONE: Record<ZoneKind, string> = {
  warning: "#ff8a1f",
  critical: "#ff3b3b",
  containment: "#b48cff",
};

/** Site layers to hide while editing, so the operator sees only their draft. */
const LIVE_ZONE_LAYERS = [
  "warning-fill",
  "warning-line",
  "critical-fill",
  "critical-line",
  "containment-fill",
  "containment-line",
];

export interface ZoneEditor {
  state: EditorState;
  draw: (kind: ZoneKind) => void;
  select: (id: string | null) => void;
  rename: (id: string, name: string) => void;
  setKind: (id: string, kind: ZoneKind) => void;
  remove: (id: string) => void;
  place: () => void;
  reset: (drafts: Draft[]) => void;
  /** Anchor the site at a typed or located point (WGS84). */
  setOrigin: (lat: number, lon: number) => void;
  setCarry: (on: boolean) => void;
  setCorner: (id: string, index: number, lat: number, lon: number) => void;
  addCorner: (id: string, after: number) => void;
  removeCorner: (id: string, index: number) => void;
  addZone: (kind: ZoneKind, ring: LngLat[]) => void;
}

export function useZoneEditor(
  map: MapLibreMap | null,
  active: boolean,
  initialSite: () => { drafts: Draft[]; origin: Origin },
): ZoneEditor {
  const [state, dispatch] = useReducer(reduce, undefined, () => initial());
  // Handlers are registered once per activation and read the live state through a ref,
  // so a vertex drag is not interrupted by re-registration on every pointer move.
  const latest = useRef(state);
  useEffect(() => {
    latest.current = state;
  }, [state]);

  // ---- enter / leave edit mode
  useEffect(() => {
    if (!map || !active) return;
    const site = initialSite();
    dispatch({ t: "load", drafts: site.drafts, siteOrigin: site.origin });
    addEditorLayers(map);
    for (const id of LIVE_ZONE_LAYERS) {
      if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", "none");
    }
    map.doubleClickZoom.disable();
    const canvas = map.getCanvas();
    const previousCursor = canvas.style.cursor;
    canvas.style.cursor = "crosshair";
    return () => {
      map.doubleClickZoom.enable();
      canvas.style.cursor = previousCursor;
      removeEditorLayers(map);
      for (const id of LIVE_ZONE_LAYERS) {
        if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", "visible");
      }
    };
    // initialSite is read once per activation on purpose: edits must not be
    // clobbered by the site query refetching underneath the operator.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, active]);

  // ---- redraw whenever the state changes
  useEffect(() => {
    if (!map || !active) return;
    setData(map, SHAPES, toGeoJSON(state));
    setData(map, VERTICES, vertexGeoJSON(state));
  }, [map, active, state]);

  // ---- follow a relocation, so the operator sees where the site landed
  useEffect(() => {
    const to = state.origin;
    if (!map || !active || !to || !state.carry) return;
    const box = bounds(toGeoJSON(latest.current));
    const [[west, south], [east, north]] = box;
    if (Number.isFinite(west + south + east + north)) {
      // the editing panel covers the left of the map; keep the zones clear of it
      map.fitBounds(box, {
        padding: { top: 64, bottom: 64, left: 384, right: 64 },
        maxZoom: 20,
        duration: 800,
      });
    } else {
      map.flyTo({ center: [to.lon, to.lat], zoom: Math.max(map.getZoom(), 18), duration: 800 });
    }
  }, [map, active, state.origin, state.carry]);

  // ---- pointer and keyboard
  useEffect(() => {
    if (!map || !active) return;
    let dragging: number | null = null;

    const at = (e: MapMouseEvent): LngLat => [e.lngLat.lng, e.lngLat.lat];

    const onClick = (e: MapMouseEvent) => {
      if (latest.current.placing) {
        dispatch({ t: "origin", at: at(e) });
        return;
      }
      if (latest.current.drawing) {
        dispatch({ t: "vertex", at: at(e) });
        return;
      }
      const hit = map.queryRenderedFeatures(e.point, { layers: [`${SHAPES}-fill`] })[0];
      dispatch({ t: "select", id: hit ? String(hit.properties["id"] ?? "") : null });
    };

    const onDoubleClick = (e: MapMouseEvent) => {
      if (!latest.current.drawing) return;
      e.preventDefault();
      dispatch({ t: "finish" });
    };

    const onVertexDown = (e: MapMouseEvent & { features?: GeoJSON.Feature[] }) => {
      const feature = e.features?.[0];
      if (!feature || latest.current.drawing) return;
      const index = Number(feature.properties?.["index"] ?? -1);
      if (index < 0) return;
      e.preventDefault();
      if (e.originalEvent.altKey) {
        dispatch({ t: "deleteVertex", index });
        return;
      }
      dragging = index;
      map.dragPan.disable();
    };

    const onMove = (e: MapMouseEvent) => {
      if (dragging === null) return;
      dispatch({ t: "moveVertex", index: dragging, at: at(e) });
    };

    const onUp = () => {
      if (dragging === null) return;
      dragging = null;
      map.dragPan.enable();
    };

    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return;
      if (e.key === "Escape") dispatch({ t: "cancel" });
      else if (e.key === "Enter" && (latest.current.drawing?.length ?? 0) >= MIN_VERTICES) {
        dispatch({ t: "finish" });
      } else if (e.key === "Backspace" && latest.current.drawing) {
        e.preventDefault();
        dispatch({ t: "undoVertex" });
      }
    };

    map.on("click", onClick);
    map.on("dblclick", onDoubleClick);
    map.on("mousedown", `${VERTICES}-dots`, onVertexDown);
    map.on("mousemove", onMove);
    map.on("mouseup", onUp);
    window.addEventListener("keydown", onKey);
    return () => {
      map.off("click", onClick);
      map.off("dblclick", onDoubleClick);
      map.off("mousedown", `${VERTICES}-dots`, onVertexDown);
      map.off("mousemove", onMove);
      map.off("mouseup", onUp);
      window.removeEventListener("keydown", onKey);
      map.dragPan.enable();
    };
  }, [map, active]);

  return {
    state,
    draw: useCallback((kind: ZoneKind) => {
      dispatch({ t: "draw", kind });
    }, []),
    select: useCallback((id: string | null) => {
      dispatch({ t: "select", id });
    }, []),
    rename: useCallback((id: string, name: string) => {
      dispatch({ t: "rename", id, name });
    }, []),
    setKind: useCallback((id: string, kind: ZoneKind) => {
      dispatch({ t: "setKind", id, kind });
    }, []),
    remove: useCallback((id: string) => {
      dispatch({ t: "remove", id });
    }, []),
    place: useCallback(() => {
      dispatch({ t: "placeMode" });
    }, []),
    reset: useCallback((drafts: Draft[]) => {
      dispatch({ t: "load", drafts });
    }, []),
    setOrigin: useCallback((lat: number, lon: number) => {
      dispatch({ t: "origin", at: [lon, lat] });
    }, []),
    setCarry: useCallback((on: boolean) => {
      dispatch({ t: "carry", on });
    }, []),
    setCorner: useCallback((id: string, index: number, lat: number, lon: number) => {
      dispatch({ t: "setVertex", id, index, at: [lon, lat] });
    }, []),
    addCorner: useCallback((id: string, after: number) => {
      dispatch({ t: "insertVertex", id, index: after });
    }, []),
    removeCorner: useCallback((id: string, index: number) => {
      dispatch({ t: "select", id });
      dispatch({ t: "deleteVertex", index });
    }, []),
    addZone: useCallback((kind: ZoneKind, ring: LngLat[]) => {
      dispatch({ t: "addZone", kind, ring });
    }, []),
  };
}

function setData(map: MapLibreMap, id: string, data: GeoJSON.FeatureCollection): void {
  const source = map.getSource(id);
  if (source && "setData" in source) (source as { setData: (d: unknown) => void }).setData(data);
}

const byKind = [
  "match",
  ["get", "kind"],
  "critical",
  TONE.critical,
  "containment",
  TONE.containment,
  TONE.warning,
] as const;

function addEditorLayers(map: MapLibreMap): void {
  const empty: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };
  if (!map.getSource(SHAPES)) map.addSource(SHAPES, { type: "geojson", data: empty });
  if (!map.getSource(VERTICES)) map.addSource(VERTICES, { type: "geojson", data: empty });
  if (!map.getLayer(`${SHAPES}-fill`)) {
    map.addLayer({
      id: `${SHAPES}-fill`,
      type: "fill",
      source: SHAPES,
      filter: ["==", ["geometry-type"], "Polygon"],
      paint: { "fill-color": byKind as never, "fill-opacity": 0.12 },
    });
    map.addLayer({
      id: `${SHAPES}-line`,
      type: "line",
      source: SHAPES,
      paint: {
        "line-color": byKind as never,
        "line-width": ["case", ["boolean", ["get", "selected"], false], 3, 1.75],
        "line-dasharray": [
          "case",
          ["boolean", ["get", "drawing"], false],
          ["literal", [2, 2]],
          ["literal", [1, 0]],
        ],
      },
    });
    map.addLayer({
      id: `${VERTICES}-dots`,
      type: "circle",
      source: VERTICES,
      paint: {
        "circle-radius": 5,
        "circle-color": "#0c110e",
        "circle-stroke-color": "#e9f1ec",
        "circle-stroke-width": 2,
      },
    });
  }
}

function removeEditorLayers(map: MapLibreMap): void {
  for (const id of [`${VERTICES}-dots`, `${SHAPES}-line`, `${SHAPES}-fill`]) {
    if (map.getLayer(id)) map.removeLayer(id);
  }
  for (const id of [VERTICES, SHAPES]) {
    if (map.getSource(id)) map.removeSource(id);
  }
}
