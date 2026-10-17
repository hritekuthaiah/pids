import { KIND_LABEL, areaM2, type Draft, type EditorState, type ZoneKind } from "./editor";

const KINDS: ZoneKind[] = ["warning", "critical", "containment"];
const TONE: Record<ZoneKind, string> = {
  warning: "var(--color-warning)",
  critical: "var(--color-critical)",
  containment: "#b48cff",
};

/** The editing side panel: draw, rename, retype, delete, save. */
export function ZonePanel({
  state,
  onDraw,
  onSelect,
  onRename,
  onKind,
  onRemove,
  onSave,
  onCancel,
  onPlace,
  saving,
  error,
}: {
  state: EditorState;
  onDraw: (kind: ZoneKind) => void;
  onSelect: (id: string | null) => void;
  onRename: (id: string, name: string) => void;
  onKind: (id: string, kind: ZoneKind) => void;
  onRemove: (id: string) => void;
  onSave: () => void;
  onCancel: () => void;
  onPlace: () => void;
  saving: boolean;
  error: string | null;
}) {
  const drawing = state.drawing !== null;
  return (
    <div
      className="hud absolute left-3 z-10 flex w-72 flex-col gap-2 bg-ink-900/95 p-3"
      style={{ top: "calc(var(--pids-banner-h, 0px) + 0.75rem)" }}
    >
      <div className="flex items-center justify-between">
        <span className="hud-title">Edit zones</span>
        <span className="font-mono text-[10px] text-fg-dim">{state.drafts.length} zones</span>
      </div>

      {drawing ? (
        <p className="text-[11.5px] text-fg-muted">
          Click the map to place corners
          {state.drawing && state.drawing.length >= 3
            ? " · double-click or Enter to close"
            : ` · ${String(3 - (state.drawing?.length ?? 0))} more`}
          <br />
          Backspace undoes a corner · Esc cancels
        </p>
      ) : (
        <div className="flex flex-wrap gap-1">
          {KINDS.map((k) => (
            <button
              key={k}
              type="button"
              className="btn-ghost"
              style={{ color: TONE[k], borderColor: TONE[k] }}
              onClick={() => {
                onDraw(k);
              }}
            >
              + {k}
            </button>
          ))}
        </div>
      )}

      <ul className="flex max-h-56 flex-col gap-1 overflow-y-auto">
        {state.drafts.map((d) => (
          <ZoneRow
            key={d.id}
            draft={d}
            selected={d.id === state.selected}
            onSelect={onSelect}
            onRename={onRename}
            onKind={onKind}
            onRemove={onRemove}
          />
        ))}
      </ul>

      <button
        type="button"
        className="btn-ghost"
        onClick={onPlace}
        title="Move the whole site to a point you click: zones keep their position on the ground"
      >
        {state.placing
          ? "Click the map to set the origin"
          : state.origin
            ? "Origin moved (saves with the zones)"
            : "Move site origin"}
      </button>

      {error !== null && <p className="text-[11.5px] text-[var(--color-critical)]">{error}</p>}
      <div className="flex gap-2">
        <button
          type="button"
          className="btn-primary flex-1 justify-center"
          disabled={!state.dirty || saving}
          onClick={onSave}
        >
          {saving ? "Saving…" : "Save zones"}
        </button>
        <button type="button" className="btn-ghost" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
      </div>
      <p className="text-[10.5px] text-fg-dim">
        Saving takes effect immediately: the decision engine judges live tracks against the new
        zones.
      </p>
    </div>
  );
}

function ZoneRow({
  draft,
  selected,
  onSelect,
  onRename,
  onKind,
  onRemove,
}: {
  draft: Draft;
  selected: boolean;
  onSelect: (id: string | null) => void;
  onRename: (id: string, name: string) => void;
  onKind: (id: string, kind: ZoneKind) => void;
  onRemove: (id: string) => void;
}) {
  return (
    <li
      className="flex flex-col gap-1 border-l-2 bg-ink-850/60 p-1.5"
      style={{ borderColor: selected ? TONE[draft.kind] : "transparent" }}
    >
      <div className="flex items-center gap-1">
        <input
          aria-label={`Name of ${draft.id}`}
          className="min-w-0 flex-1 bg-transparent text-[12.5px] text-fg outline-none"
          value={draft.name}
          onFocus={() => {
            onSelect(draft.id);
          }}
          onChange={(e) => {
            onRename(draft.id, e.target.value);
          }}
        />
        <button
          type="button"
          className="btn-ghost px-1 py-0 text-[10px]"
          aria-label={`Delete ${draft.id}`}
          onClick={() => {
            onRemove(draft.id);
          }}
        >
          ✕
        </button>
      </div>
      <div className="flex items-center gap-1">
        <select
          aria-label={`Kind of ${draft.id}`}
          className="bg-ink-900 font-mono text-[10.5px] text-fg-muted outline-none"
          value={draft.kind}
          onChange={(e) => {
            onKind(draft.id, e.target.value as ZoneKind);
          }}
        >
          {KINDS.map((k) => (
            <option key={k} value={k}>
              {KIND_LABEL[k]}
            </option>
          ))}
        </select>
        <span className="ml-auto font-mono text-[10px] text-fg-dim">
          {Math.round(areaM2(draft.ring)).toLocaleString()} m²
        </span>
      </div>
    </li>
  );
}
