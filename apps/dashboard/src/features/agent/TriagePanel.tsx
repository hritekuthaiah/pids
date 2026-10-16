import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { pids } from "../../lib/api";
import { errorMessage, type Triage } from "../../lib/agent";
import { TriageView } from "./TriageView";

/** Ask the agent for a second opinion on the selected alert (operator-approved proposals). */
export function TriagePanel({ alertId }: { alertId: string }) {
  const qc = useQueryClient();
  const status = useQuery({
    queryKey: ["agent-status"],
    staleTime: 60_000,
    queryFn: async () => (await pids.api.GET("/api/v1/agent/status")).data ?? null,
  });
  const key = ["triage", alertId];
  const latest = useQuery({
    queryKey: key,
    queryFn: async (): Promise<Triage | null> => {
      const { data } = await pids.api.GET("/api/v1/alerts/{alert_id}/triage", {
        params: { path: { alert_id: alertId } },
      });
      return data ?? null;
    },
  });
  const run = useMutation({
    mutationFn: async () => {
      const { data, error } = await pids.api.POST("/api/v1/alerts/{alert_id}/triage", {
        params: { path: { alert_id: alertId } },
      });
      if (!data) throw new Error(errorMessage(error, "triage failed"));
      return data;
    },
    onSuccess: (data) => qc.setQueryData(key, data),
  });
  const decide = useMutation({
    mutationFn: async ({
      index,
      decision,
    }: {
      index: number;
      decision: "approved" | "rejected";
    }) => {
      const report = latest.data;
      if (!report) throw new Error("no report");
      const { data } = await pids.api.POST("/api/v1/agent/reports/{report_id}/decisions", {
        params: { path: { report_id: report.id } },
        body: { action_index: index, decision, note: "" },
      });
      if (!data) throw new Error("decision failed");
      return data;
    },
    onSuccess: (data) => qc.setQueryData(key, data),
  });

  const available = status.data?.available ?? false;
  return (
    <div className="flex flex-col gap-2 border-t border-line pt-2">
      <div className="flex items-center justify-between">
        <span className="hud-title">Agent triage</span>
        <button
          type="button"
          className="btn-primary"
          disabled={!available || run.isPending}
          title={available ? (status.data?.model ?? "") : "No LLM configured on the server"}
          onClick={() => {
            run.mutate();
          }}
        >
          {run.isPending ? "Analysing…" : latest.data ? "Re-run" : "Ask the agent"}
        </button>
      </div>
      {!available && status.isSuccess && (
        <p className="text-[11.5px] text-fg-dim">
          The agent is off: no LLM is configured. Alerting is unaffected.
        </p>
      )}
      {run.isError && (
        <p className="text-[11.5px] text-[var(--color-critical)]">{run.error.message}</p>
      )}
      {latest.data && (
        <TriageView
          report={latest.data}
          busy={decide.isPending}
          onDecide={(index, decision) => {
            decide.mutate({ index, decision });
          }}
        />
      )}
    </div>
  );
}
