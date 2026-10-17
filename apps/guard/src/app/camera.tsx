import { useEffect, useState } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";

import { announce, cameraUrls, startCamera, stopCamera, type CameraState } from "../lib/cameraNode";
import { useGuard } from "../lib/store";
import { Button, Chip, Section } from "../ui/parts";
import { color, mono } from "../ui/theme";

/** Turn this phone into the site's camera: stream on the LAN, tell the control room. */
export default function CameraNode() {
  const { client, siteId } = useGuard();
  const [state, setState] = useState<CameraState>("off");
  const [urls, setUrls] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  // While streaming, re-announce so the console's listing does not go stale.
  useEffect(() => {
    if (state !== "on" || !client || !siteId) return;
    const url = urls[0];
    if (url === undefined) return;
    const tell = () => {
      void announce(client, siteId, url).catch(() => {
        /* the stream is what matters; the listing is a convenience */
      });
    };
    tell();
    const id = setInterval(tell, 30_000);
    return () => {
      clearInterval(id);
    };
  }, [state, client, siteId, urls]);

  const toggle = async () => {
    setError(null);
    if (state === "on") {
      stopCamera();
      setState("off");
      setUrls([]);
      return;
    }
    const next = await startCamera();
    setState(next);
    if (next === "on") {
      setTimeout(() => {
        setUrls(cameraUrls());
      }, 500);
    } else if (next === "denied") {
      setError("Camera permission was refused. Allow it in Android settings and try again.");
    } else {
      setError("This build has no camera module. Install the release APK, not Expo Go.");
    }
  };

  return (
    <ScrollView style={s.screen} contentContainerStyle={{ padding: 16 }}>
      <View style={s.row}>
        <Chip label="Camera" value={state} tone={state === "on" ? color.accent : color.dim} />
        <Chip label="Viewers" value={urls.length > 0 ? "ready" : "—"} tone={color.dim} />
      </View>

      <Section title="What this does">
        <Text style={s.body}>
          The phone becomes a camera for the perimeter system. It streams on this network only, for
          as long as this screen is on; nothing is recorded here, and no video goes to the server.
        </Text>
      </Section>

      <Button
        title={state === "on" ? "Stop camera" : "Start camera"}
        onPress={() => void toggle()}
      />
      {error !== null && <Text style={s.error}>{error}</Text>}

      {state === "on" && (
        <Section title="Type this on the laptop">
          {urls.length === 0 ? (
            <Text style={s.body}>Finding this phone's address…</Text>
          ) : (
            urls.map((u) => (
              <Text key={u} selectable style={s.url}>
                {u}
              </Text>
            ))
          )}
          <Text style={s.hint}>make edge SOURCE=&lt;the address above&gt;</Text>
        </Section>
      )}

      <Section title="Placing the phone">
        <Text style={s.body}>
          Wedge it high in a corner, lens pointing across the room, and keep it still: the control
          room maps what it sees onto the floor, and that mapping is calibrated to where the phone
          sits. Plug it in — streaming is hard on the battery.
        </Text>
      </Section>
    </ScrollView>
  );
}

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.bg },
  row: { flexDirection: "row", gap: 8 },
  body: { color: color.text, fontSize: 14, lineHeight: 20 },
  url: { color: color.accent, fontFamily: mono, fontSize: 17, marginTop: 4 },
  hint: { color: color.dim, fontFamily: mono, fontSize: 12, marginTop: 6 },
  error: { color: color.critical, marginTop: 8 },
});
