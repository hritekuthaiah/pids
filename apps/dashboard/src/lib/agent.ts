import type { components } from "@pids/api-client";

export type Triage = components["schemas"]["TriageOut"];
export type LogAnswer = components["schemas"]["QueryOut"];
export type AgentStatus = components["schemas"]["AgentStatusOut"];

export const VERDICT: Record<Triage["verdict"], { label: string; tone: string }> = {
  likely_intrusion: { label: "Likely intrusion", tone: "var(--color-critical)" },
  needs_verification: { label: "Needs verification", tone: "var(--color-warning)" },
  likely_benign: { label: "Likely benign", tone: "var(--color-phosphor)" },
};

export const PRIORITY_TONE: Record<Triage["recommended_actions"][number]["priority"], string> = {
  now: "var(--color-critical)",
  soon: "var(--color-warning)",
  optional: "var(--color-fg-dim)",
};

/** "sop-01-intrusion-response#2" -> "SOP-01 §2" */
export function procedureLabel(id: string): string {
  const m = /^sop-(\d+)[^#]*#(\d+)$/i.exec(id);
  return m ? `SOP-${m[1] ?? ""} §${m[2] ?? ""}` : id;
}

/** The interpreted filter as short human chips, so a misreading is visible at a glance. */
export function filterChips(f: Record<string, unknown>): string[] {
  const chips: string[] = [];
  const minutes = Number(f.since_minutes ?? 0);
  chips.push(
    minutes % 1440 === 0
      ? `last ${String(minutes / 1440)}d`
      : minutes % 60 === 0
        ? `last ${String(minutes / 60)}h`
        : `last ${String(minutes)}m`,
  );
  for (const key of ["levels", "zone_ids", "entity_classes", "statuses"] as const) {
    const v = f[key];
    if (Array.isArray(v) && v.length) chips.push(v.map(String).join(" | "));
  }
  if (typeof f.tag_id === "string" && f.tag_id) chips.push(`tag ${f.tag_id}`);
  if (f.track_lost_only === true) chips.push("lost tracks");
  return chips;
}

/** A readable message from an API error body (FastAPI puts it in `detail`). */
export function errorMessage(error: unknown, fallback: string): string {
  if (typeof error === "object" && error !== null && "detail" in error) {
    const detail = error.detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}
