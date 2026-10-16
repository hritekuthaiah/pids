import { LEVELS, type ThreatLevel } from "@pids/api-client";
import clsx from "clsx";
import { NavLink } from "react-router";

import { pids } from "../../lib/api";
import { LEVEL_COLOR, clock } from "../../lib/format";
import { useNow, useSession } from "../../lib/hooks";
import { useLive } from "../../state/live";

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
  const counts = levels.split(",").map(Number);
  const posture: ThreatLevel =
    [...LEVELS].reverse().find((l) => (counts[LEVELS.indexOf(l)] ?? 0) > 0) ?? "nominal";

  const age = receivedAt === null ? null : (now - receivedAt) / 1000;
  const stale = age === null || age > 5;
  const liveText = age === null ? "LIVE" : `LIVE ${age.toFixed(1)}s`;
  const link =
    status === "open" && !stale
      ? { text: liveText, tone: "var(--color-phosphor)" }
      : status === "open"
        ? { text: "NO DATA", tone: "var(--color-elevated)" }
        : { text: status.toUpperCase(), tone: "var(--color-critical)" };

  return (
    <header className="hud flex h-14 shrink-0 items-center gap-6 px-4">
      <div className="flex items-baseline gap-3">
        <span className="font-display text-2xl font-bold tracking-[0.24em]">PIDS</span>
        <span className="hidden flex-col leading-tight xl:flex">
          <span className="hud-title text-[9px]">Control room</span>
          <span className="text-[12px] text-fg-muted">{siteName}</span>
        </span>
      </div>

      <nav className="flex gap-1" aria-label="Sections">
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

      <div className="flex items-center gap-3" aria-label="Threat posture">
        <span className="hud-title">Posture</span>
        <span
          className="font-display text-sm font-bold tracking-[0.2em] uppercase"
          style={{ color: LEVEL_COLOR[posture] }}
        >
          {posture}
        </span>
        <div className="flex h-6 items-stretch gap-px">
          {LEVELS.map((l, i) => (
            <div
              key={l}
              className="flex min-w-9 items-center justify-center font-mono text-[11px]"
              style={{
                color: (counts[i] ?? 0) > 0 ? "#040605" : LEVEL_COLOR[l],
                background: (counts[i] ?? 0) > 0 ? LEVEL_COLOR[l] : "transparent",
                boxShadow: `inset 0 0 0 1px ${LEVEL_COLOR[l]}`,
              }}
              title={`${l}: ${String(counts[i] ?? 0)}`}
            >
              {counts[i] ?? 0}
            </div>
          ))}
        </div>
      </div>

      <div className="ml-auto flex items-center gap-5">
        <div className="flex gap-4 font-mono text-[13px]">
          <span>
            <span className="mr-1.5 text-[9px] text-fg-dim">LOCAL</span>
            {clock(new Date(now), timezone)}
          </span>
          <span className="text-fg-muted">
            <span className="mr-1.5 text-[9px] text-fg-dim">UTC</span>
            {clock(new Date(now), "UTC")}
          </span>
        </div>
        <span
          className="flex items-center gap-1.5 font-mono text-[11px]"
          style={{ color: link.tone }}
          aria-live="polite"
        >
          <span
            className={clsx("size-2 rounded-full", status === "open" && !stale && "animate-pulse")}
            style={{ background: link.tone }}
          />
          {link.text}
        </span>
        <button type="button" className="btn-ghost" onClick={toggleMute} aria-pressed={muted}>
          {muted ? "Sound off" : "Sound on"}
        </button>
        <div className="flex items-center gap-2">
          <span className="flex flex-col items-end leading-tight">
            <span className="text-[12px]">{session?.user.name}</span>
            <span className="hud-title text-[9px]">{session?.user.role}</span>
          </span>
          <button type="button" className="btn-ghost" onClick={() => void pids.logout()}>
            Sign out
          </button>
        </div>
      </div>
    </header>
  );
}
