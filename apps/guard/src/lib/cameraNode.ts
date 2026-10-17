/**
 * The phone as a camera node (ADR-0013): the native module captures with Camera2 and
 * serves MJPEG on the LAN; the edge node pulls that stream and runs detection on it.
 *
 * The phone never uploads video to the server — the stream stays on the local network
 * and only while the guard has this on.
 */
import type { PidsClient } from "@pids/api-client";
import { PermissionsAndroid, Platform } from "react-native";

import PidsCamera from "../../modules/pids-camera";

export type CameraState = "off" | "on" | "unavailable" | "denied";

export const DEFAULTS = { port: 8081, width: 1280, height: 720, fps: 15, quality: 70 };

async function permitted(): Promise<boolean> {
  if (Platform.OS !== "android") return false;
  const result = await PermissionsAndroid.requestMultiple([
    "android.permission.CAMERA",
    "android.permission.POST_NOTIFICATIONS",
  ]);
  return result["android.permission.CAMERA"] === "granted";
}

export async function startCamera(): Promise<CameraState> {
  if (!PidsCamera) return "unavailable"; // Expo Go / web: no native module
  if (!(await permitted())) return "denied";
  const { port, width, height, fps, quality } = DEFAULTS;
  PidsCamera.start(port, width, height, fps, quality);
  return "on";
}

export function stopCamera(): void {
  PidsCamera?.stop();
}

export function cameraUrls(): string[] {
  return PidsCamera?.streamUrls() ?? [];
}

/** Tell the control room where to find this stream, so an operator can read it off. */
export async function announce(client: PidsClient, siteId: string, url: string): Promise<void> {
  const { width, height, fps } = DEFAULTS;
  await client.api.POST("/api/v1/devices/camera", {
    body: { site_id: siteId, url, width, height, fps },
  });
}
