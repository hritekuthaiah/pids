import type { ThreatLevel } from "@pids/api-client";

export const LEVEL_COLOR: Record<ThreatLevel, string> = {
  nominal: "var(--color-nominal)",
  elevated: "var(--color-elevated)",
  warning: "var(--color-warning)",
  critical: "var(--color-critical)",
};

/** Hex values for MapLibre paint properties (CSS variables are not available there). */
export const LEVEL_HEX: Record<ThreatLevel, string> = {
  nominal: "#5f7a6e",
  elevated: "#e3ca4c",
  warning: "#ff8a1f",
  critical: "#ff3b3b",
};

/** Human labels for fusion evidence channels (pids_core.fusion.TERMS). */
export const CHANNEL_LABEL: Record<string, string> = {
  zone_warning: "Inside warning band",
  zone_critical: "Inside critical core",
  class_person: "Vision · person",
  class_vehicle: "Vision · vehicle",
  class_animal: "Vision · animal",
  persistence: "Track persistence",
  thermal_present: "Thermal · heat confirmed",
  thermal_absent: "Thermal · no heat",
  anomaly: "Behavioural anomaly",
  imminence: "Predicted breach",
  authorized_tag: "Authorised tag",
  spoof: "GPS spoof suspicion",
  corroboration: "Multi-sensor corroboration",
};

export const FLAG_LABEL: Record<string, string> = {
  CRITICAL_ZONE_BREACH: "Core breach",
  PREDICTED_BREACH: "Predicted breach",
  RECALL_FLOOR: "Recall floor",
  CONTAINMENT_BREACH: "Asset left containment",
  AUTHORIZED_TAG: "Tagged",
  SPOOF_SUSPECTED: "Spoof suspected",
  UNKNOWN_TAG: "Unknown tag",
};

export function since(iso: string, now: number = Date.now()): string {
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${String(m % 60).padStart(2, "0")}m`;
}

export function clock(date: Date, timeZone: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

/** "edge-01/48213-7" -> "edge-01 · 7"; "tag/patrol-alpha" -> "patrol-alpha". */
export function entityLabel(entityId: string): string {
  if (entityId.startsWith("tag/")) return entityId.slice(4);
  const [node, track = ""] = entityId.split("/");
  return `${node ?? entityId} · ${track.split("-").pop() ?? track}`;
}

export function humanize(id: string | null | undefined): string {
  if (!id) return "open ground";
  const words = id.replace(/-/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** "45s ago", "2 min ago", "1 h 05 min ago": how long since, in words an operator reads at a glance. */
export function ago(iso: string, now: number = Date.now()): string {
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${String(s)}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${String(m)} min ago`;
  return `${String(Math.floor(m / 60))} h ${String(m % 60).padStart(2, "0")} min ago`;
}

/** What the system is looking at, as a noun: "Person", "Vehicle", "Tag". */
export function noun(entityClass: string): string {
  if (entityClass === "unknown") return "Tag";
  return entityClass.charAt(0).toUpperCase() + entityClass.slice(1);
}

/** The assessment's numbers, said in words. Raw values stay behind "Why this rating". */
export function identityText(a: { tag_id: string | null; authorized: boolean }): string {
  if (a.tag_id === null) return "No badge";
  return a.authorized ? `Badge checks out (${a.tag_id})` : `Badge not authorised (${a.tag_id})`;
}

export function movementText(anomaly: number | null): string | null {
  if (anomaly === null) return null;
  return anomaly >= 0.6 ? "Unusual movement" : "Normal movement";
}
