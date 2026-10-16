import type { ChannelContribution } from "@pids/api-client";

import { CHANNEL_LABEL } from "../../lib/format";

/**
 * "Why is this an alarm?" — each evidence channel's contribution to the fused
 * log-odds, as a diverging bar: right (red) pushes toward threat, left (green)
 * away from it. Unavailable channels are listed separately, because "no thermal
 * coverage" is not the same as "no heat".
 */
export function FusionBreakdown({
  contributions,
  probability,
}: {
  contributions: ChannelContribution[];
  probability: number;
}) {
  const active = contributions
    .filter((c) => c.value !== null && Math.abs(c.log_odds) > 1e-3)
    .sort((a, b) => Math.abs(b.log_odds) - Math.abs(a.log_odds));
  const unavailable = contributions.filter((c) => c.value === null);
  const scale = Math.max(1, ...active.map((c) => Math.abs(c.log_odds)));

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between">
        <span className="hud-title">Fusion evidence · log-odds</span>
        <span className="font-mono text-[11px] text-fg-muted">
          P(threat) = <span className="text-fg">{probability.toFixed(2)}</span>
        </span>
      </div>
      <ul className="flex flex-col gap-1" aria-label="Evidence contributions">
        {active.map((c) => {
          const pct = (Math.abs(c.log_odds) / scale) * 50;
          const toward = c.log_odds > 0;
          return (
            <li
              key={c.channel}
              className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-0.5"
            >
              <span className="truncate text-[12px] text-fg-muted">
                {CHANNEL_LABEL[c.channel] ?? c.channel}
              </span>
              <span
                className="font-mono text-[11px]"
                style={{ color: toward ? "var(--color-critical)" : "var(--color-phosphor)" }}
              >
                {toward ? "+" : "−"}
                {Math.abs(c.log_odds).toFixed(2)}
              </span>
              <span className="relative col-span-2 h-1.5 bg-ink-700">
                <span className="absolute inset-y-0 left-1/2 w-px bg-line-strong" />
                <span
                  className="absolute inset-y-0"
                  style={{
                    left: toward ? "50%" : `${50 - pct}%`,
                    width: `${pct}%`,
                    background: toward ? "var(--color-critical)" : "var(--color-phosphor)",
                  }}
                />
              </span>
            </li>
          );
        })}
      </ul>
      {unavailable.length > 0 && (
        <p className="text-[11px] text-fg-dim">
          Unavailable (neutral):{" "}
          {unavailable.map((c) => CHANNEL_LABEL[c.channel] ?? c.channel).join(" · ")}
        </p>
      )}
    </div>
  );
}
