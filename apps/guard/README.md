# PIDS Guard — Android field app

The guard's phone does three jobs (PLT-09, ADR-0012):

1. **Alerts.** A live feed of the site's alerts. Raises and escalations at WARNING or
   above sound and vibrate on a high-importance channel. Alert detail shows what to do,
   why, and the distance and direction from the guard ("140 m NE"). It also has a
   *Navigate* button that opens the phone's map app, plus acknowledge, resolve and
   false-alarm actions.
2. **Passive badge.** A native foreground service advertises the guard's rolling BLE
   identifier, so the perimeter recognises them with no tapping or check-in. The secret
   comes from the server (`/guards/me/badge`, only the caller's own), and the id rotates
   every 30 s, screen off or not.
3. **Cooperative GPS tag.** A foreground location service shares the guard's position
   with the decision engine.
4. **Camera node (ADR-0013).** A spare phone can *be* the site camera: a native Camera2
   service streams MJPEG on the local network for the edge node to read, and tells the
   control room where to find it. Nothing is recorded on the phone, and no video goes to
   the server.

Built with Expo SDK 58 / React Native 0.88. It uses the shared `@pids/api-client`, so
its API calls are type-checked against the server's OpenAPI document.

## Build and install (no accounts needed)

Prerequisites (one-time; `brew install openjdk@17 && brew install --cask android-commandlinetools`):

```bash
export JAVA_HOME=$(/usr/libexec/java_home -v 17 2>/dev/null || echo /opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home)
export ANDROID_HOME=$HOME/Library/Android/sdk
```

```bash
pnpm -F @pids/guard prebuild                    # generates android/ (not committed)
(cd apps/guard/android && ./gradlew assembleRelease)
adb install -r apps/guard/android/app/build/outputs/apk/release/app-release.apk
```

To install on a phone, enable *Developer options → USB debugging* and connect it by
USB. The release APK bundles its JavaScript, so it runs without a dev server.

## Connect to the control room

1. On the laptop, run `make up-lan`. It prints the address to type into the app.
2. Sign in with a guard account (the demo guards are seeded from `SEED_GUARD_PASSWORD`).
3. Tap **Badge on**, then **Share position**, and allow the Bluetooth, location and
   notification prompts.

The phone and laptop must be on the same network. The demo LAN uses HTTP; TLS is
tracked in #33.

## Push notifications

Alerts arrive over the live WebSocket and are raised locally on the phone, which works
while the app or one of its foreground services is running. Remote push through
Expo/FCM also works when the build has an EAS project id and Firebase credentials.
Both need accounts the team creates; the server's worker already sends them.

## Checks

```bash
pnpm -F @pids/guard typecheck && pnpm -F @pids/guard lint && pnpm -F @pids/guard test
```
