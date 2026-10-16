import type { ReactNode } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { color, mono } from "./theme";

export function Chip({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <View style={[s.chip, { borderColor: tone }]}>
      <Text style={s.chipLabel}>{label}</Text>
      <Text style={[s.chipValue, { color: tone }]}>{value}</Text>
    </View>
  );
}

export function Button({
  title,
  onPress,
  tone = color.accent,
  disabled,
}: {
  title: string;
  onPress: () => void;
  tone?: string;
  disabled?: boolean;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        s.button,
        { borderColor: tone, opacity: disabled ? 0.4 : pressed ? 0.7 : 1 },
      ]}
    >
      <Text style={[s.buttonText, { color: tone }]}>{title}</Text>
    </Pressable>
  );
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <View style={s.section}>
      <Text style={s.sectionTitle}>{title}</Text>
      {children}
    </View>
  );
}

const s = StyleSheet.create({
  chip: { borderWidth: 1, borderRadius: 4, paddingHorizontal: 8, paddingVertical: 4, minWidth: 92 },
  chipLabel: { color: color.dim, fontSize: 10, letterSpacing: 1.5, textTransform: "uppercase" },
  chipValue: { fontFamily: mono, fontSize: 13, fontWeight: "700" },
  button: {
    borderWidth: 1.5,
    borderRadius: 4,
    paddingVertical: 14,
    alignItems: "center",
    marginTop: 10,
  },
  buttonText: { fontSize: 15, fontWeight: "800", letterSpacing: 2, textTransform: "uppercase" },
  section: { marginTop: 18 },
  sectionTitle: {
    color: color.dim,
    fontSize: 11,
    letterSpacing: 2,
    textTransform: "uppercase",
    marginBottom: 6,
  },
});
