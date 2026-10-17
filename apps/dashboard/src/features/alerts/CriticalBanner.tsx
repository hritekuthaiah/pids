import { useEffect } from "react";

import { alarm } from "../../lib/alarm";
import { entityLabel, humanize, since } from "../../lib/format";
import { useNow } from "../../lib/hooks";
import { unackedCritical, useLive } from "../../state/live";
import { useAlertAction } from "./actions";

/** Full-width breach band + audible alarm while any CRITICAL alert is unacknowledged. */
export function CriticalBanner() {
  const alerts = useLive((s) => s.alerts);
  const muted = useLive((s) => s.muted);
  const toggleMute = useLive((s) => s.toggleMute);
  const select = useLive((s) => s.selectAlert);
  const action = useAlertAction();
  const now = useNow(1000);
  const critical = unackedCritical(alerts).sort((a, b) => a.opened_at.localeCompare(b.opened_at));
  const first = critical[0];

  useEffect(() => {
    if (first && !muted) alarm.start();
    else alarm.stop();
    return () => {
      alarm.stop();
    };
  }, [first, muted]);

  if (!first) return null;
  return (
    <div
      ref={publishHeight}
      role="alert"
      aria-live="assertive"
      className="absolute inset-x-0 top-0 z-20 flex items-stretch shadow-[0_8px_30px_rgb(255_59_59/0.25)]"
    >
      <div className="hazard animate-stripes w-16 shrink-0" />
      <div className="flex flex-1 items-center gap-4 bg-[#2a0707]/95 px-4 py-2.5">
        <div className="flex flex-col">
          <span className="font-display text-lg leading-tight font-bold tracking-[0.2em] text-critical">
            CRITICAL BREACH{critical.length > 1 ? ` ×${String(critical.length)}` : ""}
          </span>
          <span className="font-mono text-xs text-[#ffb3b3]">
            {first.entity_class.toUpperCase()} · {humanize(first.zone_id)} ·{" "}
            {entityLabel(first.entity_id)} · T+
            {since(first.opened_at, now)}
          </span>
        </div>
        <div className="ml-auto flex gap-2">
          <button
            type="button"
            className="btn-ghost border-[#ffb3b3]/40 text-[#ffb3b3]"
            onClick={() => {
              select(first.id);
            }}
          >
            Locate
          </button>
          <button
            type="button"
            className="btn-ghost border-[#ffb3b3]/40 text-[#ffb3b3]"
            onClick={toggleMute}
            aria-pressed={muted}
          >
            {muted ? "Unmute" : "Silence"}
          </button>
          <button
            type="button"
            className="btn-danger"
            disabled={action.isPending}
            onClick={() => {
              action.mutate({ alert: first, action: { kind: "acknowledge" } });
            }}
          >
            Acknowledge
          </button>
        </div>
      </div>
      <div className="hazard animate-stripes w-16 shrink-0" />
    </div>
  );
}

/**
 * Write the banner's height onto its container as `--pids-banner-h`, so map controls
 * can sit below it. It grows with the number of criticals, so a fixed offset would
 * leave the controls buried exactly when an operator needs them.
 */
function publishHeight(el: HTMLDivElement | null): () => void {
  const parent = el?.parentElement;
  if (!el || !parent) return () => undefined;
  const observer = new ResizeObserver(([entry]) => {
    parent.style.setProperty("--pids-banner-h", `${String(entry?.contentRect.height ?? 0)}px`);
  });
  observer.observe(el);
  return () => {
    observer.disconnect();
    parent.style.removeProperty("--pids-banner-h");
  };
}
