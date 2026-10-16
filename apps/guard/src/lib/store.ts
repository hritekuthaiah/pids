import type { Alert, LiveStatus, PidsClient, User } from "@pids/api-client";
import { create } from "zustand";

export interface GuardState {
  server: string;
  client: PidsClient | null;
  user: User | null;
  siteId: string | null;
  alerts: Record<string, Alert>;
  live: LiveStatus;
  sharing: boolean;
  badge: "off" | "on" | "unavailable" | "denied";
  lastFix: { lat: number; lon: number; accuracy: number } | null;
  setAlerts: (alerts: Alert[]) => void;
  upsert: (alert: Alert) => void;
  set: (patch: Partial<GuardState>) => void;
  signOut: () => void;
}

export const useGuard = create<GuardState>((set) => ({
  server: "",
  client: null,
  user: null,
  siteId: null,
  alerts: {},
  live: "closed",
  sharing: false,
  badge: "off",
  lastFix: null,
  setAlerts: (alerts) => {
    set({ alerts: Object.fromEntries(alerts.map((a) => [a.id, a])) });
  },
  upsert: (alert) => {
    set((s) => ({ alerts: { ...s.alerts, [alert.id]: alert } }));
  },
  set: (patch) => {
    set(patch);
  },
  signOut: () => {
    set({ user: null, siteId: null, alerts: {}, live: "closed" });
  },
}));
