import type { Alert } from "@pids/api-client";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { pids } from "../../lib/api";
import { useLive } from "../../state/live";

type Action =
  | { kind: "acknowledge" }
  | { kind: "resolve"; resolution: "resolved" | "false_alarm"; note?: string };

/** Operator lifecycle actions. The server also pushes the change over the
 *  WebSocket; applying the response locally keeps the UI instant either way. */
export function useAlertAction() {
  const apply = useLive((s) => s.apply);
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ alert, action }: { alert: Alert; action: Action }): Promise<Alert> => {
      const path = { params: { path: { alert_id: alert.id } } };
      const res =
        action.kind === "acknowledge"
          ? await pids.api.POST("/api/v1/alerts/{alert_id}/acknowledge", path)
          : await pids.api.POST("/api/v1/alerts/{alert_id}/resolve", {
              ...path,
              body: { resolution: action.resolution, note: action.note ?? "" },
            });
      if (!res.data) throw new Error(`Action failed (${String(res.response.status)})`);
      return res.data;
    },
    onSuccess: (updated) => {
      apply({ type: "alert", event: updated.status, alert: updated });
      void qc.invalidateQueries({ queryKey: ["alert", updated.id] });
      void qc.invalidateQueries({ queryKey: ["alerts-log"] });
    },
  });
}
