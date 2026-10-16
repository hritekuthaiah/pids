import { useState, type SyntheticEvent } from "react";

import { pids } from "../../lib/api";

export function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: SyntheticEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await pids.login(email.trim().toLowerCase(), password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="grid h-full place-items-center p-6">
      <div className="animate-rise w-full max-w-sm">
        <div className="mb-6 flex items-end justify-between">
          <div>
            <div className="font-display text-4xl font-bold tracking-[0.2em] text-fg">PIDS</div>
            <div className="hud-title mt-1">Perimeter Intrusion Detection · Control Room</div>
          </div>
          <span className="font-mono text-[10px] text-critical">● RESTRICTED</span>
        </div>
        <form
          onSubmit={(e) => void submit(e)}
          className="hud flex flex-col gap-4 p-6"
          aria-label="Operator sign-in"
        >
          <label className="flex flex-col gap-1.5">
            <span className="hud-title">Operator ID</span>
            <input
              className="field"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
              }}
              required
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="hud-title">Passphrase</span>
            <input
              className="field"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
              }}
              required
            />
          </label>
          {error && (
            <p
              role="alert"
              className="border-l-2 border-critical bg-critical/10 px-3 py-2 text-sm text-critical"
            >
              {error}
            </p>
          )}
          <button type="submit" className="btn-primary justify-center py-2" disabled={busy}>
            {busy ? "Authenticating…" : "Sign in"}
          </button>
          <p className="text-[11px] leading-relaxed text-fg-dim">
            Access is logged. Sessions end when this tab is closed. No biometric data is collected
            by this system.
          </p>
        </form>
      </div>
    </main>
  );
}
