/** Alert logic for the guard: what is live, what is new, what to do. Pure; unit-tested. */
import { levelRank, type Alert, type AlertMessage } from "@pids/api-client";

export const ACTIVE = new Set(["open", "acknowledged"]);

export function isActive(a: Alert): boolean {
  return ACTIVE.has(a.status);
}

/** Active first, most severe first, newest first — same order as the console. */
export function sortAlerts(alerts: Iterable<Alert>): Alert[] {
  return [...alerts].sort(
    (x, y) =>
      Number(isActive(y)) - Number(isActive(x)) ||
      levelRank(y.max_level) - levelRank(x.max_level) ||
      Date.parse(y.opened_at) - Date.parse(x.opened_at),
  );
}

/** Should this server message buzz the guard's phone? Only raises and escalations. */
export function shouldNotify(msg: AlertMessage): boolean {
  return (
    (msg.event === "raised" || msg.event === "escalated") &&
    levelRank(msg.alert.level) >= levelRank("warning")
  );
}

const CLASS_WORD: Record<string, string> = {
  person: "Person",
  vehicle: "Vehicle",
  animal: "Animal",
  unknown: "Contact",
};

export function headline(a: Alert): string {
  const who = CLASS_WORD[a.entity_class] ?? "Contact";
  const where = a.zone_id ? a.zone_id.replace(/-/g, " ") : "open ground";
  return `${who} · ${where}`;
}

/** Standing instruction by level until the agent layer cites the site SOP (AIL-07). */
export function instruction(level: string, trackLost: boolean): string {
  if (trackLost)
    return "Contact lost by the cameras. Search the last known position; report what you find.";
  switch (level) {
    case "critical":
      return "Respond now. Approach the position with care, keep radio contact, do not engage alone.";
    case "warning":
      return "Move to observe. Confirm who it is and report; the control room is watching the feed.";
    case "elevated":
      return "Be aware. No action needed unless the control room asks.";
    default:
      return "No action needed.";
  }
}

export function ago(iso: string, now = Date.now()): string {
  const s = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  if (s < 60) return `${String(s)}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${String(m)}m ago`;
  return `${String(Math.floor(m / 60))}h ${String(m % 60)}m ago`;
}
