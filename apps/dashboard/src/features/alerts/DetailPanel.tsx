import type { Alert, ThreatAssessment } from "@pids/api-client";
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { Chip, LevelBadge, Panel, Stat } from "../../components/ui";
import { pids } from "../../lib/api";
import {
  FLAG_LABEL,
  LEVEL_COLOR,
  entityLabel,
  identityText,
  movementText,
  noun,
} from "../../lib/format";
import { useZoneName } from "../../lib/hooks";
import { useLive } from "../../state/live";
import { TriagePanel } from "../agent/TriagePanel";
import { useAlertAction } from "./actions";
import { FusionBreakdown } from "./FusionBreakdown";

/**
 * The selected contact, in the order an operator asks: what and where, what to do,
 * and only then why the system rated it so (folded away until opened).
 */
export function DetailPanel() {
  const entityId = useLive((s) => s.selectedEntityId);
  const alertId = useLive((s) => s.selectedAlertId);
  const live = useLive((s) => (entityId ? s.entities[entityId] : undefined));
  const alert = useLive((s) => (alertId ? s.alerts[alertId] : undefined));
  const zoneName = useZoneName();
  // prefer the live assessment; fall back to the alert's last snapshot when the
  // entity is no longer being tracked
  const a: ThreatAssessment | undefined = live ?? alert?.assessment;

  if (!a) {
    return (
      <Panel title="Selected" className="h-[46%]">
        <div className="flex flex-1 items-center justify-center p-6 text-center text-sm text-fg-dim">
          Select an alert, or someone on the map, to see what is happening and what to do.
        </div>
      </Panel>
    );
  }

  const movement = movementText(a.anomaly_score);
  return (
    <Panel title={`Selected ${noun(a.entity_class).toLowerCase()}`} className="h-[46%]">
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3">
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-2">
            <LevelBadge level={a.level} />
            {!live && <Chip tone="var(--color-elevated)">No longer tracked</Chip>}
          </div>
          <h3 className="text-lg leading-tight font-semibold text-fg">
            {noun(a.entity_class)} in {zoneName(a.zone_id)}
          </h3>
          {a.time_to_breach_s != null && (
            <p className="text-sm font-semibold text-warning">
              Could reach the protected core in about {a.time_to_breach_s.toFixed(0)} s
            </p>
          )}
          <p className="text-sm text-fg-muted">
            {identityText(a)}
            {movement && ` · ${movement}`}
            {a.spoof_suspicion >= 0.5 && (
              <span className="text-critical"> · Badge may be spoofed</span>
            )}
          </p>
        </div>

        {alert && <Actions alert={alert} />}
        {alertId && <TriagePanel alertId={alertId} />}

        <Fold title="Why this rating">
          <div className="flex items-end gap-4">
            <div
              className="font-mono text-4xl leading-none font-semibold"
              style={{ color: LEVEL_COLOR[a.level] }}
              title="Threat score out of 100"
            >
              {a.score}
            </div>
            <div className="grid flex-1 grid-cols-3 gap-2">
              <Stat
                label="Behaviour"
                value={a.anomaly_score != null ? a.anomaly_score.toFixed(2) : "—"}
              />
              <Stat
                label="Spoof"
                value={a.spoof_suspicion.toFixed(2)}
                tone={a.spoof_suspicion >= 0.5 ? "var(--color-critical)" : undefined}
              />
              <Stat label="Track" value={entityLabel(a.entity_id)} />
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
          <div className="font-mono text-xs text-fg-dim">sources: {a.sources.join(" · ")}</div>
        </Fold>
        {alertId && (
          <Fold title="Timeline">
            <Timeline alertId={alertId} />
          </Fold>
        )}
      </div>
    </Panel>
  );
}

function Actions({ alert }: { alert: Alert }) {
  const action = useAlertAction();
  const open = alert.status === "open";
  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap gap-1.5">
        {open && (
          <button
            type="button"
            className="btn-primary"
            disabled={action.isPending}
            onClick={() => {
              action.mutate({ alert, action: { kind: "acknowledge" } });
            }}
          >
            Acknowledge
          </button>
        )}
        <button
          type="button"
          className="btn-ghost"
          disabled={action.isPending}
          onClick={() => {
            action.mutate({ alert, action: { kind: "resolve", resolution: "resolved" } });
          }}
        >
          Resolve
        </button>
        <button
          type="button"
          className="btn-ghost"
          disabled={action.isPending}
          onClick={() => {
            action.mutate({ alert, action: { kind: "resolve", resolution: "false_alarm" } });
          }}
        >
          False alarm
        </button>
      </div>
      {action.isError && <p className="text-xs text-critical">{action.error.message}</p>}
    </div>
  );
}

function Fold({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details className="group border-t border-line pt-2">
      <summary className="hud-title cursor-pointer list-none select-none hover:text-fg">
        <span className="mr-1.5 inline-block transition-transform group-open:rotate-90">›</span>
        {title}
      </summary>
      <div className="mt-2 flex flex-col gap-3">{children}</div>
    </details>
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
    <ol className="flex flex-col border-l border-line-strong pl-3">
      {data.events.map((e, i) => (
        <li key={`${e.at}-${String(i)}`} className="relative pb-2 text-xs">
          <span className="absolute top-1.5 -left-[15.5px] size-1.5 bg-line-strong" />
          <span className="font-mono text-fg-dim">
            {new Date(e.at).toLocaleTimeString("en-GB", { hour12: false })}
          </span>{" "}
          <span className="font-semibold text-fg">{e.kind.replace("_", " ")}</span>{" "}
          <span className="text-fg-muted">{e.reason}</span>
        </li>
      ))}
    </ol>
  );
}
