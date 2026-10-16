import "../lib/location"; // registers the background location task

import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";

import { useLiveAlerts } from "../lib/live";
import { prepareNotifications, registerPush } from "../lib/notify";
import { pidsClient, savedServer, tokenStore } from "../lib/session";
import { useGuard } from "../lib/store";
import { color } from "../ui/theme";

/** Restore a saved session on launch: tokens in SecureStore + the last server used. */
function useRestoreSession(): void {
  useEffect(() => {
    const server = savedServer();
    if (!server || !tokenStore.get()) return;
    const { set, signOut } = useGuard.getState();
    const client = pidsClient(server, signOut);
    void (async () => {
      const me = await client.api.GET("/api/v1/auth/me");
      const sites = await client.api.GET("/api/v1/sites");
      if (me.data && sites.data?.[0]) {
        set({ server, client, user: me.data, siteId: sites.data[0].id });
      }
    })();
  }, []);
}

export default function RootLayout() {
  const user = useGuard((s) => s.user);
  useRestoreSession();
  useLiveAlerts();
  const client = useGuard((s) => s.client);
  useEffect(() => {
    void prepareNotifications();
  }, []);
  useEffect(() => {
    if (client && user) void registerPush(client);
  }, [client, user]);

  return (
    <>
      <StatusBar style="light" />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: color.bg },
          headerTintColor: color.text,
          contentStyle: { backgroundColor: color.bg },
          headerTitleStyle: { fontWeight: "800" },
        }}
      >
        <Stack.Protected guard={user !== null}>
          <Stack.Screen name="index" options={{ title: "PIDS · Guard" }} />
          <Stack.Screen name="alert/[id]" options={{ title: "Alert" }} />
        </Stack.Protected>
        <Stack.Protected guard={user === null}>
          <Stack.Screen name="login" options={{ headerShown: false }} />
        </Stack.Protected>
      </Stack>
    </>
  );
}
