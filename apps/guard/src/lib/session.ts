/**
 * The guard's session: server address and tokens live in the Android Keystore-backed
 * SecureStore, so a lost phone does not give up a long-lived credential in plain files.
 */
import { createPidsClient, type PidsClient, type TokenStore, type Tokens } from "@pids/api-client";
import * as SecureStore from "expo-secure-store";

const TOKENS = "pids.tokens";
const SERVER = "pids.server";

export const tokenStore: TokenStore = {
  get() {
    const raw = SecureStore.getItem(TOKENS);
    return raw ? (JSON.parse(raw) as Tokens) : null;
  },
  set(tokens) {
    if (tokens) SecureStore.setItem(TOKENS, JSON.stringify(tokens));
    else void SecureStore.deleteItemAsync(TOKENS);
  },
};

export function savedServer(): string {
  return SecureStore.getItem(SERVER) ?? "";
}

/** "192.168.1.20:8000" -> "http://192.168.1.20:8000" (the demo LAN has no TLS yet). */
export function normaliseServer(input: string): string {
  const s = input.trim().replace(/\/+$/, "");
  if (!s) return "";
  return /^https?:\/\//.test(s) ? s : `http://${s}`;
}

export function wsUrlFor(server: string): string {
  return `${server.replace(/^http/, "ws")}/ws`;
}

let client: PidsClient | null = null;
let clientServer = "";

export function pidsClient(server: string, onAuthLost: () => void): PidsClient {
  if (!client || clientServer !== server) {
    SecureStore.setItem(SERVER, server);
    client = createPidsClient({ baseUrl: server, store: tokenStore, onAuthLost });
    clientServer = server;
  }
  return client;
}
