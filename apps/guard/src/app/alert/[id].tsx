import type { Alert } from "@pids/api-client";
import { useLocalSearchParams } from "expo-router";
import { useState } from "react";
import { Linking, ScrollView, StyleSheet, Text, View } from "react-native";

import { ago, headline, instruction } from "../../lib/alerts";
import { heading, mapsUri } from "../../lib/geo";
import { useGuard } from "../../lib/store";
import { Button, Section } from "../../ui/parts";
import { color, levelColor, mono } from "../../ui/theme";

export default function AlertDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const alert = useGuard((s) => s.alerts[id]);
  const { client, upsert, lastFix } = useGuard();
  const [busy, setBusy] = useState(false);
  if (!alert) return <Text style={s.missing}>This alert is no longer available.</Text>;
  const tone = levelColor(alert.level);

  const act = async (run: () => Promise<{ data?: Alert }>) => {
    setBusy(true);
    try {
      const { data } = await run();
      if (data) upsert(data);
    } finally {
      setBusy(false);
    }
  };
  const path = { params: { path: { alert_id: alert.id } } };

  return (
    <ScrollView style={s.screen} contentContainerStyle={{ padding: 16, paddingBottom: 40 }}>
      <View style={[s.band, { backgroundColor: tone }]}>
        <Text style={s.bandText}>{alert.level.toUpperCase()}</Text>
        <Text style={s.bandScore}>{alert.score}</Text>
      </View>
      <Text style={s.title}>{headline(alert)}</Text>
      <Text style={s.meta}>
        opened {ago(alert.opened_at)} · {alert.status}
        {alert.tag_id ? ` · tag ${alert.tag_id}` : ""}
      </Text>

      <Section title="What to do">
        <Text style={s.instruction}>{instruction(alert.level, alert.track_lost)}</Text>
      </Section>
      <Section title="Why">
        <Text style={s.body}>{alert.reason}</Text>
      </Section>
      <Section title="Where">
        <Text style={s.where}>
          {lastFix ? heading(lastFix, alert) : "Share your position to see distance and direction"}
        </Text>
        <Text style={s.coords}>
          {alert.lat.toFixed(6)}, {alert.lon.toFixed(6)}
        </Text>
        <Button
          title="Navigate"
          onPress={() => void Linking.openURL(mapsUri(alert, headline(alert)))}
        />
      </Section>

      {client && alert.status === "open" ? (
        <Button
          title="Acknowledge — on my way"
          tone={color.warning}
          disabled={busy}
          onPress={() =>
            void act(() => client.api.POST("/api/v1/alerts/{alert_id}/acknowledge", path))
          }
        />
      ) : null}
      {client && (alert.status === "open" || alert.status === "acknowledged") ? (
        <View style={s.resolve}>
          <View style={{ flex: 1 }}>
            <Button
              title="Resolved"
              disabled={busy}
              onPress={() =>
                void act(() =>
                  client.api.POST("/api/v1/alerts/{alert_id}/resolve", {
                    ...path,
                    body: { resolution: "resolved", note: "resolved by guard on scene" },
                  }),
                )
              }
            />
          </View>
          <View style={{ width: 10 }} />
          <View style={{ flex: 1 }}>
            <Button
              title="False alarm"
              tone={color.dim}
              disabled={busy}
              onPress={() =>
                void act(() =>
                  client.api.POST("/api/v1/alerts/{alert_id}/resolve", {
                    ...path,
                    body: { resolution: "false_alarm", note: "false alarm, checked on scene" },
                  }),
                )
              }
            />
          </View>
        </View>
      ) : null}
    </ScrollView>
  );
}

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.bg },
  missing: { color: color.dim, padding: 24 },
  band: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    borderRadius: 4,
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  bandText: { color: "#000", fontSize: 18, fontWeight: "900", letterSpacing: 4 },
  bandScore: { color: "#000", fontFamily: mono, fontSize: 24, fontWeight: "900" },
  title: {
    color: color.text,
    fontSize: 24,
    fontWeight: "800",
    marginTop: 14,
    textTransform: "capitalize",
  },
  meta: { color: color.dim, fontFamily: mono, marginTop: 4 },
  instruction: { color: color.text, fontSize: 18, lineHeight: 26, fontWeight: "600" },
  body: { color: color.text, fontSize: 15, lineHeight: 22 },
  where: { color: color.accent, fontFamily: mono, fontSize: 22, fontWeight: "800" },
  coords: { color: color.dim, fontFamily: mono, marginTop: 2 },
  resolve: { flexDirection: "row" },
});
