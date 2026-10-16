import type { Alert } from "@pids/api-client";
import clsx from "clsx";

import { Chip, LevelBadge, Panel } from "../../components/ui";
import { FLAG_LABEL, LEVEL_COLOR, entityLabel, humanize, since } from "../../lib/format";
import { useNow } from "../../lib/hooks";
import { sortAlerts, useLive } from "../../state/live";
import { useAlertAction } from "./actions";

export function AlertQueue() {
  const alerts = useLive((s) => s.alerts);
  const sorted = sortAlerts(alerts);
  const open = sorted.filter((a) => a.status === "open").length;
  return (
    <Panel
      title="Alert queue"
      right={
        <span className="font-mono text-[11px] text-fg-muted">
          <span className={open ? "text-critical" : undefined}>{open} open</span> ·{" "}
          {sorted.length - open} ack
        </span>
      }
      className="min-h-0 flex-1"
    >
      <ol className="min-h-0 flex-1 overflow-y-auto" aria-label="Active alerts">
        {sorted.length === 0 && (
          <li className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center">
            <span className="font-display text-xs tracking-[0.3em] text-phosphor">
              PERIMETER QUIET
            </span>
            <span className="text-xs text-fg-dim">No active alerts. Tracking continues.</span>
          </li>
        )}
        {sorted.map((a, i) => (
          <AlertCard key={a.id} alert={a} index={i} />
        ))}
      </ol>
    </Panel>
  );
}

function AlertCard({ alert, index }: { alert: Alert; index: number }) {
  const now = useNow(1000);
  const selected = useLive((s) => s.selectedAlertId === alert.id);
  const select = useLive((s) => s.selectAlert);
  const action = useAlertAction();
  const color = LEVEL_COLOR[alert.max_level as keyof typeof LEVEL_COLOR];
  const acked = alert.status === "acknowledged";
  const flags = alert.assessment.flags.filter((f) => f !== "CRITICAL_ZONE_BREACH");

  return (
    <li
      className={clsx(
        "animate-rise group relative cursor-pointer border-b border-line py-2.5 pr-3 pl-4 transition-colors",
        selected ? "bg-ink-700" : "hover:bg-ink-800",
        acked && "opacity-70",
      )}
      style={{ animationDelay: `${Math.min(index, 8) * 30}ms` }}
      onClick={() => {
        select(alert.id);
      }}
      aria-current={selected}
    >
      <span
        className={clsx(
          "absolute inset-y-0 left-0 w-1",
          !acked && alert.max_level === "critical" && "animate-blink",
        )}
        style={{ background: color }}
      />
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <LevelBadge level={alert.max_level} />
          <span className="font-display text-[11px] font-semibold tracking-[0.14em] text-fg uppercase">
            {alert.entity_class}
          </span>
        </div>
        <span className="font-mono text-[11px] text-fg-muted" title={alert.opened_at}>
          T+{since(alert.opened_at, now)}
        </span>
      </div>
      <div className="mt-1 flex items-baseline justify-between gap-2">
        <span className="truncate text-[13px] text-fg">{humanize(alert.zone_id)}</span>
        <span className="font-mono text-[11px] text-fg-dim">{entityLabel(alert.entity_id)}</span>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1">
        <span className="font-mono text-[11px]" style={{ color }}>
          {alert.score}/100
        </span>
        {alert.track_lost && <Chip tone="var(--color-elevated)">Track lost</Chip>}
        {alert.cleared_at && <Chip>Left zone</Chip>}
        {flags.map((f) => (
          <Chip key={f} tone={f === "SPOOF_SUSPECTED" ? "var(--color-critical)" : undefined}>
            {FLAG_LABEL[f] ?? f}
          </Chip>
        ))}
      </div>
      <div
        className="mt-2 flex gap-1.5"
        onClick={(e) => {
          e.stopPropagation();
        }}
      >
        {!acked && (
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
      {action.isError && <p className="mt-1 text-[11px] text-critical">{action.error.message}</p>}
    </li>
  );
}
