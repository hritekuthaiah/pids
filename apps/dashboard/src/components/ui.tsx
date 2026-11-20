import type { ThreatLevel } from "@pids/api-client";
import clsx from "clsx";
import type { ReactNode } from "react";

import { LEVEL_COLOR } from "../lib/format";

export function Panel({
  title,
  right,
  className,
  children,
}: {
  title?: ReactNode;
  right?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={clsx("hud flex min-h-0 flex-col", className)}>
      {title !== undefined && (
        <header className="flex items-center justify-between border-b border-line px-3 py-2">
          <h2 className="hud-title">{title}</h2>
          {right}
        </header>
      )}
      {children}
    </section>
  );
}

export function LevelBadge({ level, className }: { level: string; className?: string }) {
  const color = LEVEL_COLOR[level as ThreatLevel];
  return (
    <span
      className={clsx(
        "font-display inline-flex items-center gap-1.5 px-1.5 py-0.5 text-xs font-bold",
        className,
      )}
      style={{
        color,
        boxShadow: `inset 0 0 0 1px ${color}`,
        background: `color-mix(in oklab, ${color} 12%, transparent)`,
      }}
    >
      <span className="size-1.5" style={{ background: color }} />
      {level.charAt(0).toUpperCase() + level.slice(1)}
    </span>
  );
}

export function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="font-display text-xs text-fg-dim">{label}</span>
      <span className="font-mono text-sm" style={tone ? { color: tone } : undefined}>
        {value}
      </span>
    </div>
  );
}

export function Chip({ children, tone }: { children: ReactNode; tone?: string }) {
  return (
    <span
      className="font-display px-1.5 py-px text-xs font-semibold text-fg-muted"
      style={{ boxShadow: `inset 0 0 0 1px ${tone ?? "var(--color-line-strong)"}`, color: tone }}
    >
      {children}
    </span>
  );
}
