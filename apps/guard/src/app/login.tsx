import { useState } from "react";
import { KeyboardAvoidingView, StyleSheet, Text, TextInput, View } from "react-native";

import { normaliseServer, pidsClient, savedServer } from "../lib/session";
import { useGuard } from "../lib/store";
import { Button } from "../ui/parts";
import { color, mono } from "../ui/theme";

export default function Login() {
  const [server, setServer] = useState(savedServer().replace(/^https?:\/\//, ""));
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const signIn = async () => {
    setBusy(true);
    setError(null);
    try {
      const base = normaliseServer(server);
      const { set, signOut } = useGuard.getState();
      const client = pidsClient(base, signOut);
      const user = await client.login(email.trim(), password);
      const { data: sites } = await client.api.GET("/api/v1/sites");
      const site = sites?.[0];
      if (!site) throw new Error("No site is configured on this server");
      set({ server: base, client, user, siteId: site.id });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <KeyboardAvoidingView behavior="padding" style={s.screen}>
      <Text style={s.brand}>PIDS</Text>
      <Text style={s.sub}>GUARD · FIELD UNIT</Text>
      <View style={s.form}>
        <Text style={s.label}>Control-room server</Text>
        <TextInput
          style={s.input}
          value={server}
          onChangeText={setServer}
          placeholder="192.168.1.20:8000"
          placeholderTextColor={color.dim}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
        />
        <Text style={s.label}>Email</Text>
        <TextInput
          style={s.input}
          value={email}
          onChangeText={setEmail}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="email-address"
          textContentType="username"
        />
        <Text style={s.label}>Password</Text>
        <TextInput
          style={s.input}
          value={password}
          onChangeText={setPassword}
          secureTextEntry
          textContentType="password"
        />
        {error ? <Text style={s.error}>{error}</Text> : null}
        <Button
          title={busy ? "Signing in…" : "Sign in"}
          onPress={() => void signIn()}
          disabled={busy || !server || !email || !password}
        />
      </View>
    </KeyboardAvoidingView>
  );
}

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.bg, padding: 24, justifyContent: "center" },
  brand: { color: color.text, fontSize: 44, fontWeight: "900", letterSpacing: 10 },
  sub: { color: color.critical, fontSize: 12, letterSpacing: 4, marginBottom: 28 },
  form: { borderTopWidth: 1, borderColor: color.line, paddingTop: 16 },
  label: {
    color: color.dim,
    fontSize: 11,
    letterSpacing: 2,
    textTransform: "uppercase",
    marginTop: 12,
  },
  input: {
    color: color.text,
    borderBottomWidth: 1,
    borderColor: color.line,
    paddingVertical: 8,
    fontFamily: mono,
    fontSize: 16,
  },
  error: { color: color.critical, marginTop: 12 },
});
