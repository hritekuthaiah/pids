import { createPidsClient, type TokenStore, type Tokens } from "@pids/api-client";

const KEY = "pids.session";

/**
 * Session-scoped token storage: closing the console tab ends the session, which is
 * the right default for a shared control-room workstation.
 */
export const tokenStore: TokenStore = {
  get() {
    const raw = sessionStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Tokens) : null;
  },
  set(tokens) {
    if (tokens) sessionStorage.setItem(KEY, JSON.stringify(tokens));
    else sessionStorage.removeItem(KEY);
    window.dispatchEvent(new Event("pids:session"));
  },
};

export const pids = createPidsClient({
  baseUrl: window.location.origin,
  store: tokenStore,
  onAuthLost: () => window.dispatchEvent(new Event("pids:session")),
});

export const wsUrl = `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws`;
