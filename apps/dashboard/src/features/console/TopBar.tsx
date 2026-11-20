import { LEVELS, type ThreatLevel } from "@pids/api-client";
import clsx from "clsx";
import { NavLink } from "react-router";

import { pids } from "../../lib/api";
import { LEVEL_COLOR, clock } from "../../lib/format";
import { useNow, useSession } from "../../lib/hooks";
import { useLive } from "../../state/live";

/** The site's state in one phrase, coloured only when something needs attention. */
function statusText(counts: Record<ThreatLevel, number>): {
  text: string;
  level: ThreatLevel;
} {
  if (counts.critical > 0)
    return { text: `Critical · ${String(counts.critical)}`, level: "critical" };
  if (counts.warning > 0) return { text: `Warning · ${String(counts.warning)}`, level: "warning" };
  if (counts.elevated > 0)
    return { text: `Watching ${String(counts.elevated)}`, level: "elevated" };
  return { text: "All clear", level: "nominal" };
}

export function TopBar({ siteName, timezone }: { siteName: string; timezone: string }) {
  const now = useNow(1000);
  const session = useSession();
  const status = useLive((s) => s.status);
  const receivedAt = useLive((s) => s.receivedAt);
  const muted = useLive((s) => s.muted);
  const toggleMute = useLive((s) => s.toggleMute);
  const levels = useLive((s) => {
    const counts: Record<ThreatLevel, number> = {
      nominal: 0,
      elevated: 0,
      warning: 0,
      critical: 0,
    };
    for (const e of Object.values(s.entities)) counts[e.level] += 1;
    return LEVELS.map((l) => counts[l]).join(",");
  });
  const [nominal = 0, elevated = 0, warning = 0, critical = 0] = levels.split(",").map(Number);
  const site = statusText({ nominal, elevated, warning, critical });
  const calm = site.level === "nominal";

  // The link is only worth a glance when it is broken: a quiet dot while live, words when not.
  const age = receivedAt === null ? null : (now - receivedAt) / 1000;
  const healthy = status === "open" && age !== null && age <= 5;
  const problem =
    status !== "open" ? "Reconnecting…" : age === null || age > 5 ? "No data from sensors" : null;

  return (
    <header className="hud flex h-14 shrink-0 items-center gap-5 px-4">
      <div className="flex min-w-0 items-baseline gap-3">
        <span className="shrink-0 font-brand text-xl font-bold tracking-[0.2em]">PIDS</span>
        <span className="hidden max-w-64 truncate text-sm text-fg-muted xl:inline" title={siteName}>
          {siteName}
        </span>
      </div>

      <nav className="flex shrink-0 gap-1" aria-label="Sections">
        {[
          ["/", "Console"],
          ["/alerts", "Alert log"],
          ["/tags", "Tags"],
        ].map(([to, label]) => (
          <NavLink
            key={to}
            to={to ?? "/"}
            end
            className={({ isActive }) =>
              clsx(isActive ? "btn-primary" : "btn-ghost", "border-transparent whitespace-nowrap")
            }
          >
            {label}
          </NavLink>
        ))}
      </nav>

      <span
        role="status"
        aria-label="Site status"
        className="inline-flex shrink-0 items-center gap-2 px-3 py-1 text-sm font-semibold"
        style={
          calm
            ? {
                color: "var(--color-fg-muted)",
                boxShadow: "inset 0 0 0 1px var(--color-line-strong)",
              }
            : {
                color: LEVEL_COLOR[site.level],
                boxShadow: `inset 0 0 0 1px ${LEVEL_COLOR[site.level]}`,
                background: `color-mix(in oklab, ${LEVEL_COLOR[site.level]} 14%, transparent)`,
              }
        }
      >
        <span
          className="size-2 rounded-full"
          style={{ background: calm ? "var(--color-fg-dim)" : LEVEL_COLOR[site.level] }}
        />
        {site.text}
      </span>

      <div className="ml-auto flex shrink-0 items-center gap-4 whitespace-nowrap">
        {problem ? (
          <span
            className="text-sm font-semibold"
            style={{ color: status !== "open" ? "var(--color-critical)" : "var(--color-elevated)" }}
            aria-live="polite"
          >
            {problem}
          </span>
        ) : (
          <span
            className="flex items-center gap-1.5 text-xs text-fg-dim"
            title={age === null ? undefined : `Last update ${age.toFixed(1)} s ago`}
          >
            <span
              className={clsx("size-2 rounded-full", healthy ? "bg-phosphor-dim" : "bg-fg-dim")}
            />
            Live
          </span>
        )}
        <span
          className="font-mono text-sm text-fg-muted"
          title={`${timezone} · ${clock(new Date(now), "UTC")} UTC`}
        >
          {clock(new Date(now), timezone)}
        </span>
        <div className="flex items-center gap-1 border-l border-line pl-4">
          <button
            type="button"
            className="btn-ghost border-transparent"
            onClick={toggleMute}
            aria-pressed={muted}
          >
            {muted ? "Sound off" : "Sound on"}
          </button>
          <span
            className="max-w-36 truncate px-2 text-sm text-fg-muted"
            title={`${session?.user.name ?? ""} · ${session?.user.role ?? ""}`}
          >
            {session?.user.name}
          </span>
          <button
            type="button"
            className="btn-ghost border-transparent"
            onClick={() => void pids.logout()}
          >
            Sign out
          </button>
        </div>
      </div>
    </header>
  );
}
