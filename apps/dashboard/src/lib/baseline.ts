import { levelRank, type ThreatAssessment } from "@pids/api-client";

/**
 * The naive line-crossing geofence PIDS is measured against (pids_core.baseline, PLT-11),
 * recomputed from the live assessments so the console can show it beside PIDS.
 *
 * Naive: every contact inside a zone alarms, whatever its class, behaviour or level. Like
 * the evaluation baseline it is honest rather than a straw man, so a GPS device on the
 * whitelist that no camera sees does not alarm; a camera track still does, badge or not,
 * because a naive geofence cannot tie a badge to a track.
 */
export function isNaiveAlarm(a: ThreatAssessment): boolean {
  if (a.zone_id === null) return false;
  const seenByCamera = a.sources.some((s) => s.startsWith("vision:"));
  return seenByCamera || !a.authorized;
}

/** PIDS raises an alert from WARNING up (pids_core.alerts.AlertPolicy.raise_at). */
export function isPidsAlarm(a: ThreatAssessment): boolean {
  return levelRank(a.level) >= levelRank("warning");
}

export interface BaselineCounts {
  naive: number;
  pids: number;
}

/** How many of the current contacts each system is alarming on right now. */
export function countNow(entities: readonly ThreatAssessment[]): BaselineCounts {
  let naive = 0;
  let pids = 0;
  for (const e of entities) {
    if (isNaiveAlarm(e)) naive += 1;
    if (isPidsAlarm(e)) pids += 1;
  }
  return { naive, pids };
}

/** Distinct contacts each system has alarmed on since `startedAt` (server time). */
export interface BaselineTally {
  naive: Record<string, true>;
  pids: Record<string, true>;
  startedAt: string | null;
}

export const emptyTally: BaselineTally = { naive: {}, pids: {}, startedAt: null };

/** Fold one live snapshot into the tally; returns the same object when nothing changed. */
export function accumulate(
  tally: BaselineTally,
  entities: readonly ThreatAssessment[],
  at: string,
): BaselineTally {
  let { naive, pids } = tally;
  for (const e of entities) {
    if (isNaiveAlarm(e) && !naive[e.entity_id]) naive = { ...naive, [e.entity_id]: true };
    if (isPidsAlarm(e) && !pids[e.entity_id]) pids = { ...pids, [e.entity_id]: true };
  }
  if (naive === tally.naive && pids === tally.pids && tally.startedAt !== null) return tally;
  return { naive, pids, startedAt: tally.startedAt ?? at };
}

/** One line comparing the two totals, for the foot of the panel. */
export function verdict({ naive, pids }: BaselineCounts): string {
  if (naive === 0) {
    return pids === 0 ? "No zone entries yet" : "PIDS alerted before any zone entry";
  }
  const pct = Math.round((100 * (naive - pids)) / naive);
  if (pct > 0) return `${pct}% fewer alarms than the naive geofence`;
  if (pct < 0) return `${-pct}% more alarms than the naive geofence`;
  return "As many alarms as the naive geofence";
}
