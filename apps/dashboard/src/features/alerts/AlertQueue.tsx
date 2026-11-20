import type { Alert } from "@pids/api-client";
import clsx from "clsx";

import { Chip, LevelBadge, Panel } from "../../components/ui";
import { LEVEL_COLOR, ago, entityLabel, noun } from "../../lib/format";
import { useNow, useZoneName } from "../../lib/hooks";
import { sortAlerts, useLive } from "../../state/live";
import { useAlertAction } from "./actions";

export function AlertQueue() {
  const alerts = useLive((s) => s.alerts);
  const sorted = sortAlerts(alerts);
  const open = sorted.filter((a) => a.status === "open").length;
  return (
    <Panel
      title="Alerts"
      right={
        <span className="text-xs text-fg-muted">
          <span className={open ? "font-semibold text-fg" : undefined}>{open} open</span>
          {sorted.length - open > 0 && ` · ${String(sorted.length - open)} acknowledged`}
        </span>
      }
      className="min-h-0 flex-1"
    >
      <ol className="min-h-0 flex-1 overflow-y-auto" aria-label="Active alerts">
        {sorted.length === 0 && (
          <li className="flex h-full flex-col items-center justify-center gap-1 p-8 text-center">
            <span className="text-sm font-semibold text-fg">All clear</span>
            <span className="text-xs text-fg-dim">No active alerts. Tracking continues.</span>
          </li>
        )}
        {sorted.map((a) => (
          <AlertCard key={a.id} alert={a} />
        ))}
      </ol>
    </Panel>
  );
}

/** The one tag worth showing on a card, most important first. */
function cardTag(alert: Alert): { text: string; tone?: string } | null {
  const flags = alert.assessment.flags;
  if (flags.includes("SPOOF_SUSPECTED"))
    return { text: "Badge may be spoofed", tone: "var(--color-critical)" };
  if (alert.track_lost) return { text: "Track lost", tone: "var(--color-elevated)" };
  if (alert.cleared_at) return { text: "Left the zone" };
  if (flags.includes("CONTAINMENT_BREACH"))
    return { text: "Left containment", tone: "var(--color-containment)" };
  if (alert.assessment.authorized) return { text: "Badge OK" };
  if (flags.includes("PREDICTED_BREACH"))
    return { text: "Heading for the core", tone: "var(--color-warning)" };
  return null;
}

function AlertCard({ alert }: { alert: Alert }) {
  const now = useNow(1000);
  const zoneName = useZoneName();
  const selected = useLive((s) => s.selectedAlertId === alert.id);
  const select = useLive((s) => s.selectAlert);
  const action = useAlertAction();
  const color = LEVEL_COLOR[alert.max_level as keyof typeof LEVEL_COLOR];
  const acked = alert.status === "acknowledged";
  const tag = cardTag(alert);

  return (
    <li
      className={clsx(
        "relative cursor-pointer border-b border-line py-3 pr-3 pl-4 transition-colors",
        selected ? "bg-ink-700" : "hover:bg-ink-800",
        acked && "opacity-60",
      )}
      onClick={() => {
        select(alert.id);
      }}
      aria-current={selected}
      title={`${entityLabel(alert.entity_id)} · score ${String(alert.score)}/100`}
    >
      <span className="absolute inset-y-0 left-0 w-1" style={{ background: color }} />
      <div className="flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-2">
          <LevelBadge level={alert.max_level} />
          <span className="truncate text-sm font-semibold text-fg">
            {noun(alert.entity_class)} in {zoneName(alert.zone_id)}
          </span>
        </span>
        <span className="shrink-0 text-xs text-fg-muted" title={alert.opened_at}>
          {ago(alert.opened_at, now)}
        </span>
      </div>
      <div className="mt-2 flex min-h-7 items-center justify-between gap-2">
        <span>{tag && <Chip tone={tag.tone}>{tag.text}</Chip>}</span>
        {acked ? (
          <span className="text-xs text-fg-dim">Acknowledged</span>
        ) : (
          <button
            type="button"
            className="btn-primary"
            disabled={action.isPending}
            onClick={(e) => {
              e.stopPropagation();
              action.mutate({ alert, action: { kind: "acknowledge" } });
            }}
          >
            Acknowledge
          </button>
        )}
      </div>
      {action.isError && <p className="mt-1 text-xs text-critical">{action.error.message}</p>}
    </li>
  );
}
