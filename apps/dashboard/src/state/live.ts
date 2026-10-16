import {
  levelRank,
  type Alert,
  type LiveStatus,
  type ServerMessage,
  type ThreatAssessment,
} from "@pids/api-client";
import { create } from "zustand";

export const TRAIL_POINTS = 40;

export interface LiveData {
  entities: Record<string, ThreatAssessment>;
  trails: Record<string, [number, number][]>;
  alerts: Record<string, Alert>;
  serverAt: string | null;
  receivedAt: number | null;
}

export const emptyLive: LiveData = {
  entities: {},
  trails: {},
  alerts: {},
  serverAt: null,
  receivedAt: null,
};

const ACTIVE = new Set(["open", "acknowledged"]);

/** Pure reducer: apply one server message. Exported for tests. */
export function reduce(state: LiveData, msg: ServerMessage, now: number = Date.now()): LiveData {
  switch (msg.type) {
    case "live": {
      const entities: Record<string, ThreatAssessment> = {};
      const trails: Record<string, [number, number][]> = {};
      for (const e of msg.entities) {
        entities[e.entity_id] = e;
        const prev = state.trails[e.entity_id] ?? [];
        trails[e.entity_id] = [...prev, [e.position.lon, e.position.lat] as [number, number]].slice(
          -TRAIL_POINTS,
        );
      }
      return { ...state, entities, trails, serverAt: msg.at, receivedAt: now };
    }
    case "alerts_snapshot": {
      const alerts: Record<string, Alert> = {};
      for (const a of msg.alerts) alerts[a.id] = a;
      return { ...state, alerts };
    }
    case "alert": {
      const { [msg.alert.id]: _previous, ...others } = state.alerts;
      const alerts = ACTIVE.has(msg.alert.status)
        ? { ...others, [msg.alert.id]: msg.alert }
        : others;
      return { ...state, alerts };
    }
  }
}

/** Active alerts, most urgent first: unacknowledged before acknowledged, then
 *  by severity, then newest. */
export function sortAlerts(alerts: Record<string, Alert>): Alert[] {
  return Object.values(alerts).sort(
    (a, b) =>
      Number(a.status === "acknowledged") - Number(b.status === "acknowledged") ||
      levelRank(b.max_level) - levelRank(a.max_level) ||
      b.opened_at.localeCompare(a.opened_at),
  );
}

/** Unacknowledged CRITICAL alerts — what drives the banner and the alarm. */
export function unackedCritical(alerts: Record<string, Alert>): Alert[] {
  return Object.values(alerts).filter((a) => a.status === "open" && a.max_level === "critical");
}

interface LiveStore extends LiveData {
  status: LiveStatus;
  selectedAlertId: string | null;
  selectedEntityId: string | null;
  muted: boolean;
  apply: (msg: ServerMessage) => void;
  setStatus: (s: LiveStatus) => void;
  selectAlert: (id: string | null) => void;
  selectEntity: (id: string | null) => void;
  toggleMute: () => void;
  reset: () => void;
}

export const useLive = create<LiveStore>((set) => ({
  ...emptyLive,
  status: "closed",
  selectedAlertId: null,
  selectedEntityId: null,
  muted: false,
  apply: (msg) => {
    set((s) => reduce(s, msg));
  },
  setStatus: (status) => {
    set({ status });
  },
  selectAlert: (id) => {
    set((s) => ({
      selectedAlertId: id,
      selectedEntityId: id ? (s.alerts[id]?.entity_id ?? s.selectedEntityId) : s.selectedEntityId,
    }));
  },
  selectEntity: (id) => {
    set((s) => ({
      selectedEntityId: id,
      selectedAlertId:
        Object.values(s.alerts).find((a) => a.entity_id === id)?.id ??
        (id ? null : s.selectedAlertId),
    }));
  },
  toggleMute: () => {
    set((s) => ({ muted: !s.muted }));
  },
  reset: () => {
    set({ ...emptyLive, selectedAlertId: null, selectedEntityId: null });
  },
}));
