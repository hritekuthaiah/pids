import { useMutation, useQueryClient } from "@tanstack/react-query";

import { errorMessage } from "../../lib/agent";
import { pids } from "../../lib/api";
import type { toPayload } from "./editor";

/** Save the drawn zones. The server validates them, so its message is the one to show. */
export function useSaveZones(siteId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: ReturnType<typeof toPayload>) => {
      const { data, error } = await pids.api.PUT("/api/v1/sites/{site_id}/geometry", {
        params: { path: { site_id: siteId } },
        body,
      });
      if (!data) throw new Error(errorMessage(error, "could not save the zones"));
      return data;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["site"] });
    },
  });
}
