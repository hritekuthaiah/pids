import type { Alert } from "@pids/api-client";
import { Link, router } from "expo-router";
import { useMemo } from "react";
import { FlatList, Pressable, StyleSheet, Text, View } from "react-native";

import { ago, headline, isActive, sortAlerts } from "../lib/alerts";
import { startBadge, stopBadge } from "../lib/badge";
import { heading } from "../lib/geo";
import { startSharing, stopSharing } from "../lib/location";
import { useGuard } from "../lib/store";
import { Button, Chip } from "../ui/parts";
import { color, levelColor, mono } from "../ui/theme";

function Row({ a }: { a: Alert }) {
  const fix = useGuard((s) => s.lastFix);
  const tone = levelColor(a.level);
  return (
    <Link href={{ pathname: "/alert/[id]", params: { id: a.id } }} asChild>
      <Pressable style={[s.row, { borderLeftColor: tone, opacity: isActive(a) ? 1 : 0.5 }]}>
        <View style={{ flex: 1 }}>
          <Text style={[s.level, { color: tone }]}>
            {a.level.toUpperCase()} {a.track_lost ? "· LOST" : ""}
          </Text>
          <Text style={s.title}>{headline(a)}</Text>
          <Text style={s.meta}>
            {ago(a.opened_at)} · {a.status}
            {fix ? ` · ${heading(fix, a)}` : ""}
          </Text>
        </View>
        <Text style={[s.score, { color: tone }]}>{a.score}</Text>
      </Pressable>
    </Link>
  );
}

export default function Alerts() {
  const { alerts, live, sharing, badge, user, set, client } = useGuard();
  const list = useMemo(() => sortAlerts(Object.values(alerts)), [alerts]);
  const activeCount = list.filter(isActive).length;

  const toggleSharing = async () => {
    if (sharing) {
      await stopSharing();
      set({ sharing: false });
    } else {
      set({ sharing: await startSharing() });
    }
  };
  const toggleBadge = async () => {
    if (badge === "on") {
      stopBadge();
      set({ badge: "off" });
    } else if (client) {
      set({ badge: await startBadge(client) });
    }
  };

  return (
    <View style={s.screen}>
      <View style={s.chips}>
        <Chip label="Feed" value={live} tone={live === "open" ? color.accent : color.warning} />
        <Chip
          label="Active"
          value={String(activeCount)}
          tone={activeCount ? color.critical : color.nominal}
        />
        <Chip label="Badge" value={badge} tone={badge === "on" ? color.accent : color.dim} />
        <Chip
          label="Position"
          value={sharing ? "shared" : "off"}
          tone={sharing ? color.accent : color.dim}
        />
      </View>
      <FlatList
        data={list}
        keyExtractor={(a) => a.id}
        renderItem={({ item }) => <Row a={item} />}
        ListEmptyComponent={<Text style={s.empty}>No alerts. The perimeter is quiet.</Text>}
        contentContainerStyle={{ paddingBottom: 24 }}
      />
      <View style={s.footer}>
        <Text style={s.who}>
          {user?.name} · tag {user?.tag_id ?? "none"}
        </Text>
        <View style={s.actions}>
          <View style={{ flex: 1 }}>
            <Button
              title={badge === "on" ? "Badge off" : "Badge on"}
              onPress={() => void toggleBadge()}
            />
          </View>
          <View style={{ width: 10 }} />
          <View style={{ flex: 1 }}>
            <Button
              title={sharing ? "Stop sharing" : "Share position"}
              onPress={() => void toggleSharing()}
            />
          </View>
        </View>
        <View style={s.actions}>
          <View style={{ flex: 1 }}>
            <Button
              title="Use this phone as a camera"
              onPress={() => {
                router.push("/camera");
              }}
            />
          </View>
        </View>
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.bg, paddingHorizontal: 14 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8, paddingVertical: 12 },
  row: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: color.panel,
    borderLeftWidth: 5,
    borderRadius: 4,
    padding: 12,
    marginBottom: 8,
  },
  level: { fontSize: 11, fontWeight: "900", letterSpacing: 2 },
  title: {
    color: color.text,
    fontSize: 17,
    fontWeight: "700",
    marginTop: 2,
    textTransform: "capitalize",
  },
  meta: { color: color.dim, fontFamily: mono, fontSize: 12, marginTop: 4 },
  score: { fontFamily: mono, fontSize: 26, fontWeight: "900", marginLeft: 10 },
  empty: { color: color.dim, textAlign: "center", marginTop: 48 },
  footer: { borderTopWidth: 1, borderColor: color.line, paddingVertical: 10 },
  who: { color: color.dim, fontSize: 12 },
  actions: { flexDirection: "row" },
});
