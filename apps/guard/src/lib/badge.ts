/**
 * The phone as a passive BLE badge (ADR-0012). The server hands this guard their own
 * badge secret; the native foreground service advertises the rolling identifier and
 * rotates it every window, screen off or not.
 */
import type { PidsClient } from "@pids/api-client";
import { PermissionsAndroid, Platform } from "react-native";

import PidsBadge from "../../modules/pids-badge";

export type BadgeState = "on" | "off" | "unavailable" | "denied";

async function permitted(): Promise<boolean> {
  if (Platform.OS !== "android") return false;
  if (Platform.Version < 31) return true; // pre-Android 12: install-time permissions
  const result = await PermissionsAndroid.requestMultiple([
    "android.permission.BLUETOOTH_ADVERTISE",
    "android.permission.POST_NOTIFICATIONS",
  ]);
  return result["android.permission.BLUETOOTH_ADVERTISE"] === "granted";
}

export async function startBadge(client: PidsClient): Promise<BadgeState> {
  if (!PidsBadge) return "unavailable"; // Expo Go / web: no native module
  if (!(await permitted())) return "denied";
  const { data } = await client.api.GET("/api/v1/guards/me/badge");
  if (!data) return "unavailable";
  PidsBadge.start(data.secret_hex, data.payload_prefix_hex, data.company_id, data.window_s);
  return "on";
}

export function stopBadge(): void {
  PidsBadge?.stop();
}

export function badgeRunning(): boolean {
  return PidsBadge?.isRunning() ?? false;
}
