/**
 * What each camera can see, and how to turn a point in its image into a point on the
 * map (ADR-0013). The edge node publishes the homography it calibrated; the console
 * applies it, so a click on the live preview lands where that pixel is on the ground.
 */
import { useQuery } from "@tanstack/react-query";

import type { components } from "@pids/api-client";

import { pids } from "./api";

/**
 * As the API client hands it over: JSON arrays, not tuples (openapi-fetch widens the
 * schema's fixed-length `image_size`), so read it through `imageSize` below.
 */
export type NodeView = Omit<components["schemas"]["NodeView"], "image_size"> & {
  image_size: number[];
};

/** The camera's frame size, defaulting to a harmless 1x1 if the wire disagrees. */
export function imageSize(view: NodeView): [number, number] {
  const [w = 1, h = 1] = view.image_size;
  return [w, h];
}

const M_PER_DEG_LAT = 111_320;

/** Image pixel -> site metres (east, north), or null at or above the horizon. */
export function pixelToGround(view: NodeView, x: number, y: number): [number, number] | null {
  const h = view.homography;
  const [r0, r1, r2] = h;
  if (!r0 || !r1 || !r2) return null;
  const w = (r2[0] ?? 0) * x + (r2[1] ?? 0) * y + (r2[2] ?? 0);
  // The sign of w at the image's bottom centre is the "in front of the camera" side.
  const [width, height] = imageSize(view);
  const centre = (r2[0] ?? 0) * (width / 2) + (r2[1] ?? 0) * (height - 1) + (r2[2] ?? 0);
  if (w === 0 || Math.sign(w) !== Math.sign(centre)) return null;
  return [
    ((r0[0] ?? 0) * x + (r0[1] ?? 0) * y + (r0[2] ?? 0)) / w,
    ((r1[0] ?? 0) * x + (r1[1] ?? 0) * y + (r1[2] ?? 0)) / w,
  ];
}

/** Site metres -> [lon, lat] on the local tangent plane, as the site itself defines it. */
export function groundToLngLat(view: NodeView, east: number, north: number): [number, number] {
  const lat = view.origin.lat + north / M_PER_DEG_LAT;
  const lon =
    view.origin.lon + east / (M_PER_DEG_LAT * Math.cos((view.origin.lat * Math.PI) / 180));
  return [lon, lat];
}

/** A click on the preview, in displayed pixels, as a point on the map. */
export function previewPointToLngLat(
  view: NodeView,
  xRatio: number,
  yRatio: number,
): { lngLat: [number, number]; east: number; north: number } | null {
  const [width, height] = imageSize(view);
  const ground = pixelToGround(view, xRatio * width, yRatio * height);
  if (!ground) return null;
  const [east, north] = ground;
  return { lngLat: groundToLngLat(view, east, north), east, north };
}

/** Camera footprints as GeoJSON, for the map to draw what is really covered. */
export function footprintGeoJSON(views: NodeView[]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: views
      .filter((v) => v.footprint.length >= 3)
      .map((v) => ({
        type: "Feature",
        id: `view:${v.node_id}`,
        properties: { node_id: v.node_id, rms_m: v.calibration_rms_m },
        geometry: {
          type: "Polygon",
          coordinates: [
            [
              ...v.footprint.map((p): [number, number] => [p.lon, p.lat]),
              [v.footprint[0]?.lon ?? 0, v.footprint[0]?.lat ?? 0],
            ],
          ],
        },
      })),
  };
}

export function useNodeViews(siteId: string) {
  return useQuery({
    queryKey: ["node-views", siteId],
    refetchInterval: 20_000,
    queryFn: async (): Promise<NodeView[]> => {
      const { data } = await pids.api.GET("/api/v1/sites/{site_id}/views", {
        params: { path: { site_id: siteId } },
      });
      return data ?? [];
    },
  });
}
