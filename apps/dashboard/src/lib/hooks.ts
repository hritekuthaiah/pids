import { connectLive, type Tokens } from "@pids/api-client";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, useSyncExternalStore } from "react";

import { useLive } from "../state/live";
import { pids, tokenStore, wsUrl } from "./api";

function subscribeSession(cb: () => void): () => void {
  window.addEventListener("pids:session", cb);
  return () => {
    window.removeEventListener("pids:session", cb);
  };
}

let cachedRaw: string | null = null;
let cachedTokens: Tokens | null = null;

/** The current session, re-rendering on login/logout/refresh/expiry. */
export function useSession(): Tokens | null {
  return useSyncExternalStore(subscribeSession, () => {
    const raw = sessionStorage.getItem("pids.session");
    if (raw !== cachedRaw) {
      cachedRaw = raw;
      cachedTokens = tokenStore.get();
    }
    return cachedTokens;
  });
}

/** A clock that re-renders every `ms` milliseconds. */
export function useNow(ms = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => {
      setNow(Date.now());
    }, ms);
    return () => {
      clearInterval(id);
    };
  }, [ms]);
  return now;
}

export interface SiteGeo {
  id: string;
  name: string;
  timezone: string;
  center: [number, number];
  zones: { id: string; name: string; kind: string }[];
  geojson: GeoJSON.FeatureCollection;
}

export function useSite() {
  return useQuery({
    queryKey: ["site"],
    staleTime: Infinity,
    queryFn: async (): Promise<SiteGeo> => {
      const { data: sites } = await pids.api.GET("/api/v1/sites");
      const first = sites?.[0];
      if (!first) throw new Error("No site is configured on the server.");
      const { data } = await pids.api.GET("/api/v1/sites/{site_id}", {
        params: { path: { site_id: first.id } },
      });
      if (!data) throw new Error("Could not load site geometry.");
      return data as unknown as SiteGeo;
    },
  });
}

/** Keep the live WebSocket open while mounted, feeding the live store. */
export function useLiveConnection(siteId: string | undefined): void {
  const apply = useLive((s) => s.apply);
  const setStatus = useLive((s) => s.setStatus);
  useEffect(() => {
    if (!siteId) return;
    return connectLive({ client: pids, wsUrl, siteId, onMessage: apply, onStatus: setStatus });
  }, [siteId, apply, setStatus]);
}
