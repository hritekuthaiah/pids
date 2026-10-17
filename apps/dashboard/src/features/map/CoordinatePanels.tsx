import clsx from "clsx";
import { useState } from "react";

import {
  formatCoordinate,
  parseCorners,
  parseLatitude,
  parseLongitude,
  parsePair,
  type LatLon,
} from "./coords";
import { KIND_LABEL, type Draft, type LngLat, type Origin, type ZoneKind } from "./editor";

const KINDS: ZoneKind[] = ["warning", "critical", "containment"];

/** A GPS fix worse than this is no better than clicking the spot on the satellite view. */
const ROUGH_FIX_M = 25;

/**
 * One coordinate box. It keeps what you type until you leave it (or press Enter), then
 * commits if it parses and snaps back if it does not — nothing is half-applied while a
 * number is still being typed. A pasted "lat, lon" pair fills both boxes.
 */
function CoordInput({
  label,
  value,
  parse,
  onCommit,
  onPair,
}: {
  label: string;
  value: number;
  parse: (text: string) => number | null;
  onCommit: (value: number) => void;
  onPair?: (pair: LatLon) => void;
}) {
  const [bad, setBad] = useState(false);
  const shown = formatCoordinate(value);
  return (
    <input
      // a new committed value remounts the box, so it always shows what is stored
      key={shown}
      aria-label={label}
      aria-invalid={bad}
      inputMode="decimal"
      spellCheck={false}
      defaultValue={shown}
      className={clsx(
        "min-w-0 flex-1 border bg-ink-900 px-1.5 py-0.5 font-mono text-[11.5px] text-fg",
        "focus:border-phosphor focus:outline-none",
        bad ? "border-[var(--color-critical)]" : "border-line-strong",
      )}
      onChange={() => {
        setBad(false);
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter") e.currentTarget.blur();
      }}
      onBlur={(e) => {
        const text = e.currentTarget.value;
        const pair = onPair ? parsePair(text) : null;
        if (pair && onPair) {
          setBad(false);
          onPair(pair);
          return;
        }
        const parsed = parse(text);
        if (parsed === null) {
          setBad(true);
          return;
        }
        if (parsed !== value) onCommit(parsed);
      }}
    />
  );
}

type Fix = { kind: "idle" } | { kind: "locating" } | { kind: "fix"; accuracy: number };

/** Why a location request failed, in words an operator can act on. */
function geolocationMessage(err: GeolocationPositionError): string {
  if (err.code === err.PERMISSION_DENIED) {
    return "Location is blocked. Allow it for this page in the browser (and in macOS Location Services), or type the coordinates.";
  }
  if (err.code === err.TIMEOUT)
    return "No position fix yet. Try again by a window, or type the coordinates.";
  return "This device could not work out its position. Type the coordinates instead.";
}

/** Where the site is: type it, take it from this device, or click it on the map. */
export function LocationSection({
  origin,
  moved,
  carry,
  placing,
  onOrigin,
  onCarry,
  onPlace,
}: {
  origin: Origin | null;
  moved: boolean;
  carry: boolean;
  placing: boolean;
  onOrigin: (lat: number, lon: number) => void;
  onCarry: (on: boolean) => void;
  onPlace: () => void;
}) {
  const [fix, setFix] = useState<Fix>({ kind: "idle" });
  const [error, setError] = useState<string | null>(null);

  const locate = () => {
    setError(null);
    if (!window.isSecureContext || !("geolocation" in navigator)) {
      setError(
        "This browser only shares its location with https:// pages or localhost. Open the console at http://localhost, or type the coordinates.",
      );
      return;
    }
    setFix({ kind: "locating" });
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setFix({ kind: "fix", accuracy: pos.coords.accuracy });
        onOrigin(pos.coords.latitude, pos.coords.longitude);
      },
      (err) => {
        setFix({ kind: "idle" });
        setError(geolocationMessage(err));
      },
      { enableHighAccuracy: true, timeout: 20_000, maximumAge: 0 },
    );
  };

  return (
    <section className="flex flex-col gap-1.5 border-b border-line pb-2.5">
      <div className="flex items-center justify-between">
        <span className="hud-title">Site location</span>
        {moved && (
          <span className="font-mono text-[10px] text-[var(--color-warning)]">moved · unsaved</span>
        )}
      </div>
      {origin ? (
        <div className="grid grid-cols-[3.2rem_1fr] items-center gap-x-2 gap-y-1">
          <span className="text-[10.5px] text-fg-dim">Latitude</span>
          <CoordInput
            label="Site latitude"
            value={origin.lat}
            parse={parseLatitude}
            onCommit={(lat) => {
              onOrigin(lat, origin.lon);
            }}
            onPair={(p) => {
              onOrigin(p.lat, p.lon);
            }}
          />
          <span className="text-[10.5px] text-fg-dim">Longitude</span>
          <CoordInput
            label="Site longitude"
            value={origin.lon}
            parse={parseLongitude}
            onCommit={(lon) => {
              onOrigin(origin.lat, lon);
            }}
            onPair={(p) => {
              onOrigin(p.lat, p.lon);
            }}
          />
        </div>
      ) : (
        <p className="text-[11px] text-fg-dim">Loading the site's position…</p>
      )}
      <div className="flex gap-1">
        <button
          type="button"
          className="btn-primary flex-1 justify-center"
          disabled={fix.kind === "locating"}
          onClick={locate}
        >
          {fix.kind === "locating" ? "Locating…" : "Use my location"}
        </button>
        <button
          type="button"
          className={clsx("btn-ghost flex-1 justify-center", placing && "border-phosphor")}
          onClick={onPlace}
        >
          {placing ? "Click the map…" : "Pick on map"}
        </button>
      </div>
      <label className="flex items-start gap-1.5 text-[11px] text-fg-muted">
        <input
          type="checkbox"
          className="mt-0.5 accent-[var(--color-phosphor)]"
          checked={carry}
          disabled={moved}
          onChange={(e) => {
            onCarry(e.target.checked);
          }}
        />
        <span>
          Move the zones and cameras with it
          <span className="block text-[10px] text-fg-dim">
            {carry
              ? "The whole site lands on this point, keeping its size and layout."
              : "Zones stay where they are; only the site's reference point changes."}
          </span>
        </span>
      </label>
      {fix.kind === "fix" && (
        <p
          className={clsx(
            "text-[10.5px]",
            fix.accuracy > ROUGH_FIX_M ? "text-[var(--color-warning)]" : "text-fg-muted",
          )}
        >
          Fix accurate to ±{Math.round(fix.accuracy)} m
          {fix.accuracy > ROUGH_FIX_M &&
            " — rough for a room. Switch to the satellite view and use Pick on map for the exact corner."}
        </p>
      )}
      {error !== null && <p className="text-[10.5px] text-[var(--color-critical)]">{error}</p>}
      <p className="text-[10px] text-fg-dim">
        The origin is the site's south-west reference point: zones are measured east and north from
        it.
      </p>
    </section>
  );
}

/** Every corner of the selected zone as editable latitude/longitude. */
export function CornerTable({
  draft,
  onCorner,
  onAdd,
  onRemove,
}: {
  draft: Draft;
  onCorner: (id: string, index: number, lat: number, lon: number) => void;
  onAdd: (id: string, after: number) => void;
  onRemove: (id: string, index: number) => void;
}) {
  const canRemove = draft.ring.length > 3;
  return (
    <section className="flex flex-col gap-1 border-t border-line pt-2.5">
      <div className="flex items-center justify-between">
        <span className="hud-title">Corners</span>
        <span className="max-w-[10rem] truncate font-mono text-[10px] text-fg-dim">
          {draft.name}
        </span>
      </div>
      <ol className="flex max-h-44 flex-col gap-1 overflow-y-auto pr-0.5">
        {draft.ring.map(([lon, lat], i) => (
          <li key={`${draft.id}-${String(i)}`} className="flex items-center gap-1">
            <span className="w-4 text-right font-mono text-[10px] text-fg-dim">{i + 1}</span>
            <CoordInput
              label={`Latitude of corner ${String(i + 1)}`}
              value={lat}
              parse={parseLatitude}
              onCommit={(v) => {
                onCorner(draft.id, i, v, lon);
              }}
              onPair={(p) => {
                onCorner(draft.id, i, p.lat, p.lon);
              }}
            />
            <CoordInput
              label={`Longitude of corner ${String(i + 1)}`}
              value={lon}
              parse={parseLongitude}
              onCommit={(v) => {
                onCorner(draft.id, i, lat, v);
              }}
            />
            <button
              type="button"
              className="btn-ghost px-1 py-0 text-[10px]"
              aria-label={`Add a corner after corner ${String(i + 1)}`}
              title="Add a corner halfway to the next one"
              onClick={() => {
                onAdd(draft.id, i);
              }}
            >
              +
            </button>
            <button
              type="button"
              className="btn-ghost px-1 py-0 text-[10px]"
              aria-label={`Remove corner ${String(i + 1)}`}
              title={canRemove ? "Remove this corner" : "A zone needs at least three corners"}
              disabled={!canRemove}
              onClick={() => {
                onRemove(draft.id, i);
              }}
            >
              ✕
            </button>
          </li>
        ))}
      </ol>
      <p className="text-[10px] text-fg-dim">
        Latitude, longitude. Type or paste; drag a corner on the map to nudge it.
      </p>
    </section>
  );
}

/** Make a zone from a list of corners pasted from a survey, a map app or a spreadsheet. */
export function CoordinateImport({ onAdd }: { onAdd: (kind: ZoneKind, ring: LngLat[]) => void }) {
  const [kind, setKind] = useState<ZoneKind>("critical");
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);

  const add = () => {
    const parsed = parseCorners(text);
    if (!parsed.ok) {
      setError(parsed.error);
      return;
    }
    onAdd(kind, parsed.ring);
    setText("");
    setError(null);
  };

  return (
    <details className="border-t border-line pt-2.5">
      <summary className="hud-title cursor-pointer select-none">
        Add a zone from coordinates
      </summary>
      <div className="mt-1.5 flex flex-col gap-1.5">
        <textarea
          aria-label="Zone corners, one latitude and longitude per line"
          className="field h-24 resize-y px-1.5 py-1 text-[11.5px]"
          spellCheck={false}
          placeholder={"13.262000, 77.420000\n13.262000, 77.420090\n13.262050, 77.420090"}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setError(null);
          }}
        />
        <div className="flex items-center gap-1">
          <select
            aria-label="Kind of the new zone"
            className="min-w-0 flex-1 bg-ink-900 font-mono text-[10.5px] text-fg-muted outline-none"
            value={kind}
            onChange={(e) => {
              setKind(e.target.value as ZoneKind);
            }}
          >
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {KIND_LABEL[k]}
              </option>
            ))}
          </select>
          <button type="button" className="btn-primary" disabled={text.trim() === ""} onClick={add}>
            Add zone
          </button>
        </div>
        {error !== null && <p className="text-[10.5px] text-[var(--color-critical)]">{error}</p>}
        <p className="text-[10px] text-fg-dim">
          One corner per line as latitude, longitude — exactly what a map app copies. At least
          three.
        </p>
      </div>
    </details>
  );
}
