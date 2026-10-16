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
  return id.replace(/-/g, " ");
}
