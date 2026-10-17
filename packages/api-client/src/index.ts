/**
 * Typed PIDS API client shared by the control-room dashboard and the guard app.
 *
 * - Types are generated from the server's OpenAPI document (`pnpm gen:api`), so a
 *   contract change on the server is a compile error here.
 * - Access tokens are refreshed *proactively* shortly before they expire (never by
 *   replaying a failed request, whose body may already be consumed).
 * - `connectLive` keeps a WebSocket open with ticket auth and exponential backoff.
 */
import createClient, { type Middleware } from "openapi-fetch";

import type { components, paths } from "./schema";

export type { components, paths };
export type Schemas = components["schemas"];
export type ThreatAssessment = Schemas["ThreatAssessment"];
export type ThreatLevel = Schemas["ThreatLevel"];
export type ChannelContribution = Schemas["ChannelContribution"];
export type Alert = Schemas["AlertOut"];
export type AlertDetail = Schemas["AlertDetailOut"];
export type AlertStatus = Schemas["AlertStatus"];
export type LiveMessage = Schemas["LiveMessage"];
export type AlertMessage = Schemas["AlertMessage"];
export type AlertsSnapshotMessage = Schemas["AlertsSnapshotMessage"];
export type SiteChangedMessage = Schemas["SiteChangedMessage"];
export type TokenOut = Schemas["TokenOut"];
export type User = Schemas["UserOut"];
export type Tag = Schemas["TagOut"];
export type ServerMessage = LiveMessage | AlertMessage | AlertsSnapshotMessage | SiteChangedMessage;

export const LEVELS: readonly ThreatLevel[] = ["nominal", "elevated", "warning", "critical"];
export const levelRank = (l: ThreatLevel | string): number => LEVELS.indexOf(l as ThreatLevel);

export interface Tokens {
  access_token: string;
  refresh_token: string;
  user: User;
}

/** Where tokens live: sessionStorage on the web, SecureStore on the phone. */
export interface TokenStore {
  get(): Tokens | null;
  set(tokens: Tokens | null): void;
}

const REFRESH_MARGIN_S = 60;

/** Seconds until the JWT's `exp`, or 0 if it cannot be read. */
export function secondsUntilExpiry(jwt: string, now = Date.now()): number {
  try {
    const payload = jwt.split(".")[1] ?? "";
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    const exp = (JSON.parse(json) as { exp?: number }).exp ?? 0;
    return Math.max(0, exp - now / 1000);
  } catch {
    return 0;
  }
}

export interface PidsClientOptions {
  baseUrl: string;
  store: TokenStore;
  /** Called when the session cannot be refreshed (expired, revoked, reused). */
  onAuthLost?: () => void;
}

export function createPidsClient({ baseUrl, store, onAuthLost }: PidsClientOptions) {
  const api = createClient<paths>({ baseUrl });
  const bare = createClient<paths>({ baseUrl });
  let inflight: Promise<boolean> | null = null;

  async function refresh(): Promise<boolean> {
    const current = store.get();
    if (!current) return false;
    const { data } = await bare.POST("/api/v1/auth/refresh", {
      body: { refresh_token: current.refresh_token },
    });
    if (!data) {
      store.set(null);
      onAuthLost?.();
      return false;
    }
    store.set({
      access_token: data.access_token,
      refresh_token: data.refresh_token,
      user: data.user,
    });
    return true;
  }

  async function freshAccessToken(): Promise<string | null> {
    const current = store.get();
    if (!current) return null;
    if (secondsUntilExpiry(current.access_token) > REFRESH_MARGIN_S) return current.access_token;
    inflight ??= refresh().finally(() => {
      inflight = null;
    });
    return (await inflight) ? (store.get()?.access_token ?? null) : null;
  }

  const auth: Middleware = {
    async onRequest({ request }) {
      const token = await freshAccessToken();
      if (token) request.headers.set("Authorization", `Bearer ${token}`);
      return request;
    },
    onResponse({ response }) {
      if (response.status === 401) {
        store.set(null);
        onAuthLost?.();
      }
      return response;
    },
  };
  api.use(auth);

  async function login(email: string, password: string): Promise<User> {
    const { data, error, response } = await bare.POST("/api/v1/auth/login", {
      body: { email, password },
    });
    if (!data) {
      throw new Error(
        response.status === 429
          ? "Too many attempts — wait a minute."
          : response.status === 401
            ? "Invalid credentials."
            : `Login failed (${String(response.status)}): ${JSON.stringify(error)}`,
      );
    }
    store.set({
      access_token: data.access_token,
      refresh_token: data.refresh_token,
      user: data.user,
    });
    return data.user;
  }

  async function logout(): Promise<void> {
    const current = store.get();
    store.set(null);
    if (current) {
      await bare.POST("/api/v1/auth/logout", { body: { refresh_token: current.refresh_token } });
    }
  }

  return { api, login, logout, refresh, freshAccessToken };
}

export type PidsClient = ReturnType<typeof createPidsClient>;

// --------------------------------------------------------------------------- live

export type LiveStatus = "connecting" | "open" | "reconnecting" | "closed";

export interface LiveOptions {
  client: PidsClient;
  wsUrl: string; // e.g. ws://localhost:8000/ws
  siteId: string;
  onMessage: (msg: ServerMessage) => void;
  onStatus?: (status: LiveStatus) => void;
}

/** Keep a ticket-authenticated WebSocket open; returns a disposer. */
export function connectLive({
  client,
  wsUrl,
  siteId,
  onMessage,
  onStatus,
}: LiveOptions): () => void {
  let ws: WebSocket | null = null;
  let stopped = false;
  let attempt = 0;
  let keepAlive: ReturnType<typeof setInterval> | undefined;
  let retry: ReturnType<typeof setTimeout> | undefined;

  const schedule = () => {
    if (stopped) return;
    onStatus?.("reconnecting");
    const delay = Math.min(15_000, 500 * 2 ** attempt) * (0.75 + Math.random() * 0.5);
    attempt += 1;
    retry = setTimeout(() => void open(), delay);
  };

  const open = async () => {
    onStatus?.(attempt === 0 ? "connecting" : "reconnecting");
    const { data } = await client.api.POST("/api/v1/auth/ws-ticket");
    if (stopped) return;
    if (!data) {
      schedule();
      return;
    }
    const url = `${wsUrl}?ticket=${encodeURIComponent(data.ticket)}&site_id=${encodeURIComponent(siteId)}`;
    ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";
    ws.onopen = () => {
      attempt = 0;
      onStatus?.("open");
      keepAlive = setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send("ping"), 20_000);
    };
    ws.onmessage = (ev: MessageEvent<ArrayBuffer | string>) => {
      const text = typeof ev.data === "string" ? ev.data : new TextDecoder().decode(ev.data);
      if (text === "pong") return;
      onMessage(JSON.parse(text) as ServerMessage);
    };
    ws.onclose = () => {
      clearInterval(keepAlive);
      ws = null;
      schedule();
    };
  };

  void open();
  return () => {
    stopped = true;
    clearTimeout(retry);
    clearInterval(keepAlive);
    onStatus?.("closed");
    ws?.close();
  };
}
