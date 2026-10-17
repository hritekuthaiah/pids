import type { ThreatAssessment } from "@pids/api-client";
import clsx from "clsx";
import {
  Map as MapLibreMap,
  Marker,
  NavigationControl,
  ScaleControl,
  type AddLayerObject,
  type FilterSpecification,
  type GeoJSONSource,
  type StyleSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef, useState } from "react";

import { LEVEL_HEX } from "../../lib/format";
import type { SiteGeo } from "../../lib/hooks";
import { useLive } from "../../state/live";
import { draftsFrom, toPayload } from "./editor";
import { bounds, headingDeg, lerp, predictedBreachPoint } from "./geo";
import { useSaveZones } from "./saveZones";
import { useZoneEditor } from "./useZoneEditor";
import { ZonePanel } from "./ZonePanel";
import { createEntityMarker, updateEntityMarker, type EntityMarker } from "./marker";

type Basemap = "dark" | "streets" | "satellite";
const TWEEN_MS = 520;

/** Overlays start below the critical banner, which publishes its own height. */
const BELOW_BANNER = { top: "calc(var(--pids-banner-h, 0px) + 0.75rem)" } as const;

const STYLE: StyleSpecification = {
  version: 8,
  sources: {
    // Keyless basemaps only: the console must not depend on a third-party account.
    dark: {
      type: "raster",
      tiles: [
        "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
      ],
      tileSize: 256,
      maxzoom: 16,
      attribution: "Esri, HERE, Garmin, © OpenStreetMap contributors",
    },
    streets: {
      type: "raster",
      tiles: [
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
      ],
      tileSize: 256,
      maxzoom: 19,
      attribution: "Esri, HERE, Garmin, © OpenStreetMap contributors",
    },
    satellite: {
      type: "raster",
      tiles: [
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      ],
      tileSize: 256,
      // Imagery stops around z19; MapLibre over-scales the last tile above that, which
      // is what a room-sized site needs (8 m across is zoom 21-22).
      maxzoom: 19,
      attribution: "Imagery © Esri, Maxar, Earthstar Geographics",
    },
  },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": "#040605" } },
    { id: "dark", type: "raster", source: "dark", paint: { "raster-opacity": 0.85 } },
    {
      id: "streets",
      type: "raster",
      source: "streets",
      layout: { visibility: "none" },
      paint: { "raster-opacity": 0.75, "raster-saturation": -0.3, "raster-brightness-max": 0.75 },
    },
    {
      id: "satellite",
      type: "raster",
      source: "satellite",
      layout: { visibility: "none" },
      // keep imagery subdued so overlays stay legible across a room
      paint: { "raster-saturation": -0.55, "raster-brightness-max": 0.5, "raster-contrast": 0.1 },
    },
  ],
};

/** Diagonal hatch for the critical core: reads as "no-go" without hiding the ground. */
function hatch(color: string): ImageData {
  const size = 16;
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d");
  if (!g) throw new Error("2D canvas unavailable");
  g.strokeStyle = color;
  g.lineWidth = 1.5;
  g.beginPath();
  for (let o = -size; o <= size; o += 8) {
    g.moveTo(o, size);
    g.lineTo(o + size, 0);
  }
  g.stroke();
  return g.getImageData(0, 0, size, size);
}

function addSiteLayers(map: MapLibreMap, site: SiteGeo): void {
  map.addSource("site", { type: "geojson", data: site.geojson });
  map.addImage("hatch-critical", hatch("rgba(255,59,59,0.55)"));
  const isLayer = (layer: string): FilterSpecification => ["==", ["get", "layer"], layer];
  const zone = (kind: string): FilterSpecification => [
    "all",
    ["==", ["get", "layer"], "zone"],
    ["==", ["get", "kind"], kind],
  ];
  const add = (spec: AddLayerObject) => {
    map.addLayer(spec);
  };

  add({
    id: "coverage-fill",
    type: "fill",
    source: "site",
    filter: isLayer("coverage"),
    paint: { "fill-color": "#6ff2a6", "fill-opacity": 0.03 },
  });
  add({
    id: "coverage-line",
    type: "line",
    source: "site",
    filter: isLayer("coverage"),
    paint: { "line-color": "#6ff2a6", "line-opacity": 0.16, "line-width": 1 },
  });
  add({
    id: "warning-fill",
    type: "fill",
    source: "site",
    filter: zone("warning"),
    paint: { "fill-color": "#ff8a1f", "fill-opacity": 0.05 },
  });
  add({
    id: "warning-line",
    type: "line",
    source: "site",
    filter: zone("warning"),
    paint: {
      "line-color": "#ff8a1f",
      "line-opacity": 0.85,
      "line-width": 1.5,
      "line-dasharray": [4, 3],
    },
  });
  add({
    id: "critical-fill",
    type: "fill",
    source: "site",
    filter: zone("critical"),
    paint: { "fill-pattern": "hatch-critical", "fill-opacity": 0.45 },
  });
  add({
    id: "critical-line",
    type: "line",
    source: "site",
    filter: zone("critical"),
    paint: { "line-color": "#ff3b3b", "line-width": 2 },
  });
  add({
    id: "containment-fill",
    type: "fill",
    source: "site",
    filter: zone("containment"),
    paint: { "fill-color": "#b48cff", "fill-opacity": 0.1 },
  });
  add({
    id: "containment-line",
    type: "line",
    source: "site",
    filter: zone("containment"),
    paint: { "line-color": "#b48cff", "line-width": 1.5, "line-dasharray": [1, 2] },
  });
  add({
    id: "road",
    type: "line",
    source: "site",
    filter: isLayer("road"),
    paint: { "line-color": "#8fa198", "line-opacity": 0.28, "line-width": 5 },
  });
  add({
    id: "route",
    type: "line",
    source: "site",
    filter: isLayer("patrol_route"),
    paint: {
      "line-color": "#6ff2a6",
      "line-opacity": 0.3,
      "line-width": 1.2,
      "line-dasharray": [1, 3],
    },
  });
  add({
    id: "nodes",
    type: "circle",
    source: "site",
    filter: isLayer("node"),
    paint: {
      "circle-radius": 4,
      "circle-color": "#0c110e",
      "circle-stroke-color": "#6ff2a6",
      "circle-stroke-width": 1.5,
    },
  });
  add({
    id: "readers",
    type: "circle",
    source: "site",
    filter: isLayer("reader"),
    paint: {
      "circle-radius": 3.5,
      "circle-color": "#0c110e",
      "circle-stroke-color": "#b48cff",
      "circle-stroke-width": 1.5,
    },
  });

  map.addSource("trails", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
  add({
    id: "trails",
    type: "line",
    source: "trails",
    layout: { "line-cap": "round" },
    paint: { "line-color": ["get", "color"], "line-opacity": 0.4, "line-width": 1.5 },
  });
  map.addSource("vectors", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
  add({
    id: "vectors",
    type: "line",
    source: "vectors",
    filter: ["==", ["geometry-type"], "LineString"],
    paint: { "line-color": "#ff8a1f", "line-width": 1.5, "line-dasharray": [2, 2] },
  });
  add({
    id: "vector-ends",
    type: "circle",
    source: "vectors",
    filter: ["==", ["geometry-type"], "Point"],
    paint: {
      "circle-radius": 5,
      "circle-color": "rgba(0,0,0,0)",
      "circle-stroke-color": "#ff8a1f",
      "circle-stroke-width": 1.5,
    },
  });
}

function zoneLabels(map: MapLibreMap, site: SiteGeo): Marker[] {
  return site.geojson.features
    .filter((f) => f.properties?.["layer"] === "zone" && f.geometry.type === "Polygon")
    .map((f) => {
      const [[minX], [, maxY]] = bounds({ type: "FeatureCollection", features: [f] });
      const kind = String(f.properties?.["kind"]);
      const el = document.createElement("div");
      el.className = `zone-label zone-${kind}`;
      el.textContent = String(f.properties?.["name"] ?? "");
      return new Marker({ element: el, anchor: "top-left", offset: [6, 6] })
        .setLngLat([minX, maxY])
        .addTo(map);
    });
}

export function MapView({ site, canEdit = false }: { site: SiteGeo; canEdit?: boolean }) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const [basemap, setBasemap] = useState<Basemap>("dark");
  const [showCoverage, setShowCoverage] = useState(true);
  const [ready, setReady] = useState(false);
  const [loaded, setLoaded] = useState<MapLibreMap | null>(null);
  const [editing, setEditing] = useState(false);
  const selectEntity = useLive((s) => s.selectEntity);
  const editor = useZoneEditor(loaded, editing, () => draftsFrom(site.geojson));
  const save = useSaveZones(site.id);

  // ---- map lifecycle
  useEffect(() => {
    if (!container.current) return;
    const map = new MapLibreMap({
      container: container.current,
      style: STYLE,
      center: site.center,
      zoom: 16,
      dragRotate: false,
      pitchWithRotate: false,
      maxZoom: 23,
      attributionControl: { compact: true },
    });
    map.addControl(new NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new ScaleControl({ unit: "metric" }), "bottom-right");
    let labels: Marker[] = [];
    map.on("load", () => {
      addSiteLayers(map, site);
      labels = zoneLabels(map, site);
      map.resize();
      map.fitBounds(bounds(site.geojson), { padding: 48, duration: 0, maxZoom: 21 });
      setReady(true);
      setLoaded(map);
    });
    // Panels and the breach banner change the available space; keep the canvas in step.
    const observer = new ResizeObserver(() => {
      map.resize();
    });
    observer.observe(container.current);
    mapRef.current = map;
    return () => {
      observer.disconnect();
      for (const l of labels) l.remove();
      map.remove();
      mapRef.current = null;
      setReady(false);
      setLoaded(null);
    };
  }, [site]);

  // ---- basemap & layer toggles
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    for (const b of ["dark", "streets", "satellite"] as const) {
      map.setLayoutProperty(b, "visibility", basemap === b ? "visible" : "none");
    }
    for (const id of ["coverage-fill", "coverage-line"]) {
      map.setLayoutProperty(id, "visibility", showCoverage ? "visible" : "none");
    }
  }, [basemap, showCoverage, ready]);

  // ---- entities: DOM markers tweened between 2 Hz snapshots at display rate
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const markers = new Map<string, EntityMarker>();
    const tweens = new Map<string, { from: [number, number]; to: [number, number]; t0: number }>();
    let frame = 0;

    const sync = (entities: Record<string, ThreatAssessment>, selected: string | null) => {
      const now = performance.now();
      for (const [id, m] of markers) {
        if (!(id in entities)) {
          m.marker.remove();
          markers.delete(id);
          tweens.delete(id);
        }
      }
      for (const a of Object.values(entities)) {
        const to: [number, number] = [a.position.lon, a.position.lat];
        let m = markers.get(a.entity_id);
        if (!m) {
          m = createEntityMarker(a, () => {
            selectEntity(a.entity_id);
          });
          m.marker.setLngLat(to).addTo(map);
          markers.set(a.entity_id, m);
        }
        const cur = m.marker.getLngLat();
        tweens.set(a.entity_id, { from: [cur.lng, cur.lat], to, t0: now });
        updateEntityMarker(m, a, headingDeg(a), a.entity_id === selected);
      }
      const trails = useLive.getState().trails;
      void map.getSource<GeoJSONSource>("trails")?.setData({
        type: "FeatureCollection",
        features: Object.values(entities)
          .filter((a) => (trails[a.entity_id]?.length ?? 0) > 1)
          .map((a) => ({
            type: "Feature",
            properties: { color: LEVEL_HEX[a.level] },
            geometry: { type: "LineString", coordinates: trails[a.entity_id] ?? [] },
          })),
      });
      const vectors: GeoJSON.Feature[] = [];
      for (const a of Object.values(entities)) {
        const end = predictedBreachPoint(a);
        if (!end || a.level === "nominal") continue;
        vectors.push(
          {
            type: "Feature",
            properties: {},
            geometry: { type: "LineString", coordinates: [[a.position.lon, a.position.lat], end] },
          },
          { type: "Feature", properties: {}, geometry: { type: "Point", coordinates: end } },
        );
      }
      void map.getSource<GeoJSONSource>("vectors")?.setData({
        type: "FeatureCollection",
        features: vectors,
      });
    };

    const tick = () => {
      const now = performance.now();
      for (const [id, tw] of tweens) {
        const t = Math.min(1, (now - tw.t0) / TWEEN_MS);
        const e = 1 - (1 - t) ** 3;
        markers
          .get(id)
          ?.marker.setLngLat([lerp(tw.from[0], tw.to[0], e), lerp(tw.from[1], tw.to[1], e)]);
        if (t >= 1) tweens.delete(id);
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);

    const initial = useLive.getState();
    sync(initial.entities, initial.selectedEntityId);
    const unsubscribe = useLive.subscribe((s, prev) => {
      if (s.entities !== prev.entities || s.selectedEntityId !== prev.selectedEntityId) {
        sync(s.entities, s.selectedEntityId);
      }
    });
    return () => {
      unsubscribe();
      cancelAnimationFrame(frame);
      for (const m of markers.values()) m.marker.remove();
    };
  }, [ready, selectEntity]);

  // ---- follow the selected alert
  const selectedAlert = useLive((s) =>
    s.selectedAlertId ? s.alerts[s.selectedAlertId] : undefined,
  );
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !selectedAlert) return;
    map.easeTo({ center: [selectedAlert.lon, selectedAlert.lat], duration: 600 });
  }, [selectedAlert?.id, ready]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="relative h-full w-full overflow-hidden">
      {/* MapLibre forces position:relative on its container, so size it explicitly */}
      <div ref={container} className="h-full w-full" aria-label="Live site map" />
      <div
        className={clsx("absolute z-10 flex gap-1.5", editing ? "left-[19.5rem]" : "left-3")}
        style={BELOW_BANNER}
      >
        {(["dark", "streets", "satellite"] as const).map((b) => (
          <button
            key={b}
            type="button"
            className={clsx(
              basemap === b ? "btn-primary bg-ink-900/90" : "btn-ghost bg-ink-900/80",
            )}
            onClick={() => {
              setBasemap(b);
            }}
          >
            {b}
          </button>
        ))}
        <button
          type="button"
          className={clsx(showCoverage ? "btn-primary bg-ink-900/90" : "btn-ghost bg-ink-900/80")}
          onClick={() => {
            setShowCoverage((v) => !v);
          }}
        >
          Sensor cover
        </button>
        {canEdit && !editing && (
          <button
            type="button"
            className="btn-ghost bg-ink-900/80"
            onClick={() => {
              setEditing(true);
            }}
          >
            Edit zones
          </button>
        )}
      </div>
      {editing && (
        <ZonePanel
          state={editor.state}
          saving={save.isPending}
          error={save.error?.message ?? null}
          onDraw={editor.draw}
          onSelect={editor.select}
          onRename={editor.rename}
          onKind={editor.setKind}
          onRemove={editor.remove}
          onPlace={editor.place}
          onCancel={() => {
            save.reset();
            setEditing(false);
          }}
          onSave={() => {
            save.mutate(toPayload(editor.state, editor.state.origin ?? undefined), {
              onSuccess: () => {
                setEditing(false);
              },
            });
          }}
        />
      )}
      <Legend />
    </div>
  );
}

function Legend() {
  const counts = useLive((s) => {
    const c = { nominal: 0, elevated: 0, warning: 0, critical: 0 };
    for (const e of Object.values(s.entities)) c[e.level] += 1;
    return `${c.nominal},${c.elevated},${c.warning},${c.critical}`;
  });
  const [n, e, w, c] = counts.split(",").map(Number);
  return (
    <div className="hud absolute bottom-3 left-3 flex items-center gap-4 px-3 py-2 font-mono text-[11px]">
      <span className="hud-title">Tracked</span>
      {(
        [
          ["nominal", n],
          ["elevated", e],
          ["warning", w],
          ["critical", c],
        ] as const
      ).map(([lvl, v]) => (
        <span key={lvl} className="flex items-center gap-1.5" style={{ color: LEVEL_HEX[lvl] }}>
          <span className="size-2 rounded-full" style={{ background: LEVEL_HEX[lvl] }} />
          {v}
        </span>
      ))}
      <span className="flex items-center gap-1.5 text-fg-dim">
        <span className="inline-block h-0 w-4 border-t border-dashed border-warning" /> forecast
      </span>
    </div>
  );
}
