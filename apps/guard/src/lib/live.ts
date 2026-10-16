import { connectLive } from "@pids/api-client";
import { useEffect } from "react";

import { shouldNotify } from "./alerts";
import { alarm } from "./notify";
import { wsUrlFor } from "./session";
import { useGuard } from "./store";

/** Keep the alert feed live while signed in; buzz on raises and escalations. */
export function useLiveAlerts(): void {
  const client = useGuard((s) => s.client);
  const siteId = useGuard((s) => s.siteId);
  const server = useGuard((s) => s.server);

  useEffect(() => {
    if (!client || !siteId) return undefined;
    const { set, setAlerts, upsert } = useGuard.getState();
    void client.api
      .GET("/api/v1/alerts", { params: { query: { site_id: siteId, limit: 100 } } })
      .then(({ data }) => {
        if (data) setAlerts(data);
      });
    return connectLive({
      client,
      wsUrl: wsUrlFor(server),
      siteId,
      onStatus: (live) => {
        set({ live });
      },
      onMessage: (msg) => {
        if (msg.type === "alert") {
          upsert(msg.alert);
          if (shouldNotify(msg)) void alarm(msg.alert);
        } else if (msg.type === "alerts_snapshot") {
          setAlerts(msg.alerts);
        }
      },
    });
  }, [client, siteId, server]);
}
