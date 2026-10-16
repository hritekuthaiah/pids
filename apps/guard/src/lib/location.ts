/**
 * The guard's phone as a cooperative GPS tag (PLT-09): a foreground-service location
 * task posts fixes to the server, which feeds them to the decision engine exactly like
 * a hardware tag. Defined at module scope, as TaskManager requires.
 */
import * as Location from "expo-location";
import * as TaskManager from "expo-task-manager";

import { useGuard } from "./store";

export const LOCATION_TASK = "pids-guard-location";

interface LocationTaskData {
  locations: Location.LocationObject[];
}

TaskManager.defineTask<LocationTaskData>(LOCATION_TASK, async ({ data, error }) => {
  if (error) return;
  const fix = data.locations.at(-1);
  const { client, siteId } = useGuard.getState();
  if (!fix || !client || !siteId) return;
  const accuracy = fix.coords.accuracy ?? 25;
  useGuard
    .getState()
    .set({ lastFix: { lat: fix.coords.latitude, lon: fix.coords.longitude, accuracy } });
  await client.api.POST("/api/v1/guards/me/location", {
    body: {
      site_id: siteId,
      lat: fix.coords.latitude,
      lon: fix.coords.longitude,
      accuracy_m: Math.min(500, accuracy),
      at: new Date(fix.timestamp).toISOString(),
    },
  });
});

export async function startSharing(): Promise<boolean> {
  const fg = await Location.requestForegroundPermissionsAsync();
  if (!fg.granted) return false;
  await Location.requestBackgroundPermissionsAsync(); // "allow all the time" is optional
  await Location.startLocationUpdatesAsync(LOCATION_TASK, {
    accuracy: Location.Accuracy.BestForNavigation,
    timeInterval: 2000,
    distanceInterval: 1,
    foregroundService: {
      notificationTitle: "PIDS — sharing your position",
      notificationBody: "The control room sees you as a guard on patrol.",
      notificationColor: "#5fd3a8",
    },
  });
  return true;
}

export async function stopSharing(): Promise<void> {
  if (await Location.hasStartedLocationUpdatesAsync(LOCATION_TASK)) {
    await Location.stopLocationUpdatesAsync(LOCATION_TASK);
  }
}
