import { Panel } from "../../components/ui";
import { countNow, verdict } from "../../lib/baseline";
import { since } from "../../lib/format";
import { useNow } from "../../lib/hooks";
import { useLive } from "../../state/live";

/** What a naive line-crossing geofence would have alarmed on vs what PIDS raised. */
export function BaselinePanel() {
  const now = useNow(1000);
  const entities = useLive((s) => s.entities);
  const naive = useLive((s) => Object.keys(s.tally.naive).length);
  const pids = useLive((s) => Object.keys(s.tally.pids).length);
  const startedAt = useLive((s) => s.tally.startedAt);
  const resetTally = useLive((s) => s.resetTally);
  const current = countNow(Object.values(entities));

  return (
    <Panel
      title="Naive geofence vs PIDS"
      right={
        <div className="flex items-center gap-3">
          <span
            className="font-mono text-[11px] text-fg-muted"
            title={startedAt ? `Counting since ${startedAt}` : undefined}
          >
            {startedAt ? `T+${since(startedAt, now)}` : "Awaiting data"}
          </span>
          <button type="button" className="btn-ghost" onClick={resetTally}>
            Reset
          </button>
        </div>
      }
      className="min-w-0 flex-1"
    >
      <div className="grid min-h-0 flex-1 grid-cols-2 divide-x divide-line">
        <Count
          label="Naive geofence (would alarm)"
          hint="Every contact inside a zone alarms, whatever its class, behaviour or badge: the line-crossing baseline PIDS is evaluated against."
          total={naive}
          totalTone="var(--color-fg-muted)"
          now={`${current.naive} in a zone now`}
          nowTone="var(--color-fg-dim)"
        />
        <Count
          label="PIDS (alerting)"
          hint="Contacts PIDS rated WARNING or above, which is when it raises an alert."
          total={pids}
          totalTone="var(--color-fg)"
          now={`${current.pids} alerting now`}
          nowTone={current.pids > 0 ? "var(--color-warning)" : "var(--color-fg-dim)"}
        />
      </div>
      <p className="truncate border-t border-line px-3 py-1.5 text-[11px] text-fg-muted">
        {verdict({ naive, pids })} · one count per contact
      </p>
    </Panel>
  );
}

function Count({
  label,
  hint,
  total,
  totalTone,
  now,
  nowTone,
}: {
  label: string;
  hint: string;
  total: number;
  totalTone: string;
  now: string;
  nowTone: string;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      title={hint}
      className="flex min-w-0 flex-col justify-center gap-1.5 px-4 py-3"
    >
      <span className="font-display text-[10px] font-semibold tracking-[0.14em] text-fg-muted uppercase">
        {label}
      </span>
      <span
        className="font-display text-5xl leading-none font-bold 2xl:text-7xl"
        style={{ color: totalTone }}
      >
        {total}
      </span>
      <span className="font-mono text-[11px]" style={{ color: nowTone }}>
        {now}
      </span>
    </div>
  );
}
