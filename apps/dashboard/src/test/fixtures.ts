import type { Alert, ThreatAssessment, ThreatLevel } from "@pids/api-client";

export function assessment(overrides: Partial<ThreatAssessment> = {}): ThreatAssessment {
  return {
    schema_version: 1,
    site_id: "site-alpha",
    entity_id: "edge-01/123-7",
    at: "2026-10-27T04:30:00Z",
    entity_class: "person",
    position: { lat: 13.263, lon: 77.42 },
    velocity: { east: 0, north: -1.5 },
    zone_id: "perimeter-warning",
    zone_kind: "warning",
    probability: 0.82,
    score: 82,
    level: "warning",
    contributions: [
      { channel: "zone_warning", value: 1, log_odds: 1.54 },
      { channel: "class_person", value: 0.9, log_odds: 1.33 },
      { channel: "authorized_tag", value: 0, log_odds: 0 },
      { channel: "thermal_present", value: null, log_odds: 0 },
      { channel: "anomaly", value: -0.4, log_odds: -0.1 },
    ],
    tag_id: null,
    authorized: false,
    spoof_suspicion: 0,
    anomaly_score: 0.3,
    time_to_breach_s: 20,
    predicted_zone_id: "compound-critical",
    flags: ["PREDICTED_BREACH"],
    sources: ["vision:edge-01"],
    trace: {},
    ...overrides,
  };
}

export function alert(id: string, level: ThreatLevel, overrides: Partial<Alert> = {}): Alert {
  return {
    id,
    site_id: "site-alpha",
    entity_id: `edge-01/${id}`,
    status: "open",
    level,
    max_level: level,
    score: 80,
    zone_id: "compound-critical",
    entity_class: "person",
    tag_id: null,
    reason: "person in compound-critical",
    lat: 13.262,
    lon: 77.42,
    opened_at: "2026-10-27T04:30:00Z",
    updated_at: "2026-10-27T04:30:00Z",
    cleared_at: null,
    track_lost: false,
    acknowledged_by: null,
    acknowledged_at: null,
    resolved_by: null,
    resolved_at: null,
    resolution_note: null,
    assessment: assessment({ entity_id: `edge-01/${id}`, level }),
    ...overrides,
  };
}
