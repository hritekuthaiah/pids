import type { ThreatAssessment } from "@pids/api-client";
import { useQuery } from "@tanstack/react-query";

import { Chip, LevelBadge, Panel, Stat } from "../../components/ui";
import { pids } from "../../lib/api";
import { FLAG_LABEL, LEVEL_COLOR, entityLabel, humanize } from "../../lib/format";
import { useLive } from "../../state/live";
import { TriagePanel } from "../agent/TriagePanel";
import { FusionBreakdown } from "./FusionBreakdown";

export function DetailPanel() {
  const entityId = useLive((s) => s.selectedEntityId);
  const alertId = useLive((s) => s.selectedAlertId);
  const live = useLive((s) => (entityId ? s.entities[entityId] : undefined));
  const alert = useLive((s) => (alertId ? s.alerts[alertId] : undefined));
  // prefer the live assessment; fall back to the alert's last snapshot when the
  // entity is no longer being tracked
  const a: ThreatAssessment | undefined = live ?? alert?.assessment;

  if (!a) {
    return (
      <Panel title="Contact" className="h-[46%]">
        <div className="flex flex-1 items-center justify-center p-6 text-center text-xs text-fg-dim">
          Select an alert or a contact on the map to see why the system rated it the way it did.
        </div>
      </Panel>
    );
  }

  const color = LEVEL_COLOR[a.level];
  return (
    <Panel
      title={`Contact · ${entityLabel(a.entity_id)}`}
      right={
        live ? (
          <LevelBadge level={a.level} />
        ) : (
          <Chip tone="var(--color-elevated)">Not tracked</Chip>
        )
      }
      className="h-[46%]"
    >
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3">
        <div className="flex items-end gap-4">
          <div className="font-display text-5xl leading-none font-bold" style={{ color }}>
            {a.score}
          </div>
          <div className="grid flex-1 grid-cols-3 gap-2">
            <Stat label="Class" value={a.entity_class} />
            <Stat label="Zone" value={humanize(a.zone_id)} />
            <Stat
              label="To breach"
              value={a.time_to_breach_s != null ? `${a.time_to_breach_s.toFixed(0)}s` : "—"}
              tone={a.time_to_breach_s != null ? "var(--color-warning)" : undefined}
            />
            <Stat
              label="Identity"
              value={a.tag_id ?? "none"}
              tone={a.authorized ? "var(--color-phosphor)" : undefined}
            />
            <Stat
              label="Behaviour"
              value={a.anomaly_score != null ? a.anomaly_score.toFixed(2) : "—"}
            />
            <Stat
              label="Spoof"
              value={a.spoof_suspicion.toFixed(2)}
              tone={a.spoof_suspicion >= 0.5 ? "var(--color-critical)" : undefined}
            />
          </div>
        </div>
        {a.flags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {a.flags.map((f) => (
              <Chip key={f}>{FLAG_LABEL[f] ?? f}</Chip>
            ))}
          </div>
        )}
        <FusionBreakdown contributions={a.contributions} probability={a.probability} />
        <div className="font-mono text-[10px] text-fg-dim">sources: {a.sources.join(" · ")}</div>
        {alertId && <TriagePanel alertId={alertId} />}
        {alertId && <Timeline alertId={alertId} />}
      </div>
    </Panel>
  );
}

function Timeline({ alertId }: { alertId: string }) {
  const updatedAt = useLive((s) => s.alerts[alertId]?.updated_at);
  const { data } = useQuery({
    queryKey: ["alert", alertId, updatedAt],
    queryFn: async () => {
      const { data } = await pids.api.GET("/api/v1/alerts/{alert_id}/detail", {
        params: { path: { alert_id: alertId } },
      });
      return data ?? null;
    },
  });
  if (!data) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <span className="hud-title">Timeline</span>
      <ol className="flex flex-col border-l border-line-strong pl-3">
        {data.events.map((e, i) => (
          <li key={`${e.at}-${String(i)}`} className="relative pb-2 text-[12px]">
            <span className="absolute top-1.5 -left-[15.5px] size-1.5 bg-line-strong" />
            <span className="font-mono text-[10.5px] text-fg-dim">
              {new Date(e.at).toLocaleTimeString("en-GB", { hour12: false })}
            </span>{" "}
            <span className="font-display text-[10.5px] font-semibold tracking-[0.12em] text-fg uppercase">
              {e.kind.replace("_", " ")}
            </span>{" "}
            <span className="text-fg-muted">{e.reason}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
