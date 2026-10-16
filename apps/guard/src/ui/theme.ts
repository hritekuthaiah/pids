/** The control-room palette, shared in spirit with the dashboard (dark, high contrast). */
import type { ThreatLevel } from "@pids/api-client";

export const color = {
  bg: "#0a0e0d",
  panel: "#121816",
  line: "#22302b",
  text: "#e6ece9",
  dim: "#8a9a94",
  accent: "#5fd3a8",
  nominal: "#5f7a6e",
  elevated: "#e3ca4c",
  warning: "#ff8a1f",
  critical: "#ff3b3b",
} as const;

export const LEVEL_COLOR: Record<ThreatLevel, string> = {
  nominal: color.nominal,
  elevated: color.elevated,
  warning: color.warning,
  critical: color.critical,
};

export const mono = "monospace";

/** Server levels arrive as plain strings; anything unexpected renders neutral. */
export function levelColor(level: string): string {
  return (LEVEL_COLOR as Record<string, string | undefined>)[level] ?? color.dim;
}
