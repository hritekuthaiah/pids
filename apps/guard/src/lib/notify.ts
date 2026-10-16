/**
 * Alarms on the phone. Live alerts arrive over the WebSocket while the app (or one of
 * its foreground services) is running and are shown as high-importance local
 * notifications with a distinct vibration. Remote push through Expo/FCM is used as
 * well when the build has Firebase credentials (the worker already sends it).
 */
import type { Alert, PidsClient } from "@pids/api-client";
import Constants from "expo-constants";
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { Platform, Vibration } from "react-native";

import { headline } from "./alerts";

const CHANNEL = "pids-alerts";
const PATTERN = [0, 400, 200, 400, 200, 800];

Notifications.setNotificationHandler({
  handleNotification: () =>
    Promise.resolve({
      shouldPlaySound: true,
      shouldSetBadge: false,
      shouldShowBanner: true,
      shouldShowList: true,
    }),
});

export async function prepareNotifications(): Promise<boolean> {
  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync(CHANNEL, {
      name: "Intrusion alerts",
      importance: Notifications.AndroidImportance.MAX,
      vibrationPattern: PATTERN,
      lockscreenVisibility: Notifications.AndroidNotificationVisibility.PUBLIC,
      bypassDnd: true,
    });
  }
  const { granted } = await Notifications.requestPermissionsAsync();
  return granted;
}

export async function alarm(a: Alert): Promise<void> {
  Vibration.vibrate(PATTERN);
  await Notifications.scheduleNotificationAsync({
    content: {
      title: `${a.level.toUpperCase()} · ${headline(a)}`,
      body: a.reason,
      data: { alertId: a.id },
      sound: true,
    },
    trigger: Platform.OS === "android" ? { channelId: CHANNEL } : null,
  });
}

/**
 * Register for remote push when this build can (an EAS project id and Firebase
 * credentials). Without them the live feed + local alarms above still work while the
 * app or its foreground services run, so this failing is reported, not fatal.
 */
export async function registerPush(client: PidsClient): Promise<"registered" | "unavailable"> {
  const extra = Constants.expoConfig?.extra as { eas?: { projectId?: string } } | undefined;
  const projectId = extra?.eas?.projectId;
  if (!Device.isDevice || !projectId) return "unavailable";
  try {
    const { data: token } = await Notifications.getExpoPushTokenAsync({ projectId });
    await client.api.POST("/api/v1/devices/push-token", { body: { token, platform: "android" } });
    return "registered";
  } catch {
    return "unavailable";
  }
}
