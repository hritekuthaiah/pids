import clsx from "clsx";
import { useEffect, useId, useState } from "react";

import { Panel } from "../../components/ui";
import { PhoneCameras } from "./PhoneCameras";
import { EDGE_PREVIEW_URL, attemptUrl, snapshotUrl } from "../../lib/camera";

const RETRY_MS = 3000;
/** A stream that connects but delivers no first frame within this is treated as down. */
const FIRST_FRAME_MS = 8000;
const PROBE_MS = 5000;

type FeedState = "connecting" | "live" | "offline";
type Fault = "unreachable" | "no-frames";

const FEED_TONE: Record<FeedState, string> = {
  connecting: "var(--color-elevated)",
  live: "var(--color-phosphor)",
  offline: "var(--color-critical)",
};

/**
 * While live, load the edge's snapshot endpoint every PROBE_MS. Browsers fire no event
 * when an MJPEG stream dies mid-way (the <img> freezes on its last frame), so a probe
 * that errors, or is still unanswered at the next tick, is how a dead edge shows up.
 * An <img> load needs no CORS and never exposes the pixels to the page.
 */
function watchLiveness(url: string, onDead: () => void): (() => void) | undefined {
  const snapshot = snapshotUrl(url);
  if (!snapshot) return undefined;
  let pending: HTMLImageElement | null = null;
  const abandon = () => {
    if (!pending) return;
    pending.onload = null;
    pending.onerror = null;
    pending.removeAttribute("src");
    pending = null;
  };
  const id = setInterval(() => {
    if (pending) {
      abandon();
      onDead();
      return;
    }
    const probe = new Image();
    probe.onload = () => {
      pending = null;
    };
    probe.onerror = () => {
      pending = null;
      onDead();
    };
    probe.src = `${snapshot}?t=${Date.now()}`;
    pending = probe;
  }, PROBE_MS);
  return () => {
    clearInterval(id);
    abandon();
  };
}

/** Connection state of the preview <img>: the first frame makes it live; an error, no
 *  first frame or a failed liveness probe makes it offline, and while the panel is shown
 *  a fresh attempt follows every RETRY_MS. */
function useFeed(url: string, shown: boolean) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<FeedState>("connecting");
  const [fault, setFault] = useState<Fault>("unreachable");

  useEffect(() => {
    if (!shown) return;
    if (state === "live") {
      return watchLiveness(url, () => {
        setFault("unreachable");
        setState("offline");
      });
    }
    const id =
      state === "offline"
        ? setTimeout(() => {
            setAttempt((n) => n + 1);
            setState("connecting");
          }, RETRY_MS)
        : setTimeout(() => {
            setFault("no-frames");
            setState("offline");
          }, FIRST_FRAME_MS);
    return () => {
      clearTimeout(id);
    };
  }, [shown, state, url, attempt]);

  return {
    state,
    fault,
    attempt,
    src: attemptUrl(url, attempt),
    onLoad: () => {
      setState("live");
    },
    onError: () => {
      setFault("unreachable");
      setState("offline");
    },
    reconnect: () => {
      setAttempt((n) => n + 1);
      setState("connecting");
    },
  };
}

/** The edge node's annotated preview, embedded as an MJPEG <img> (ADR-0011). */
export function CameraPanel({ url = EDGE_PREVIEW_URL, siteId }: { url?: string; siteId?: string }) {
  const [shown, setShown] = useState(true);
  const feed = useFeed(url, shown);
  const bodyId = useId();

  return (
    <Panel
      title="Live camera"
      right={
        <div className="flex items-center gap-3">
          {shown && (
            <span
              role="status"
              className="flex items-center gap-1.5 font-mono text-[11px] uppercase"
              style={{ color: FEED_TONE[feed.state] }}
            >
              <span
                className={clsx("size-2 rounded-full", feed.state === "live" && "animate-pulse")}
                style={{ background: FEED_TONE[feed.state] }}
              />
              {feed.state}
            </span>
          )}
          <button
            type="button"
            className="btn-ghost"
            aria-expanded={shown}
            aria-controls={bodyId}
            onClick={() => {
              // Collapsing unmounts the <img>, closing the stream so the edge stops
              // encoding frames nobody watches; expanding opens a fresh one.
              if (!shown) feed.reconnect();
              setShown(!shown);
            }}
          >
            {shown ? "Collapse" : "Expand"}
          </button>
        </div>
      }
      className={clsx("shrink-0", shown ? "w-[360px] 2xl:w-[512px]" : "w-60")}
    >
      <div id={bodyId} className="flex min-h-0 flex-1 flex-col">
        {shown ? (
          <div className="relative aspect-video bg-ink-950">
            {feed.state !== "offline" && (
              <img
                key={feed.attempt}
                src={feed.src}
                alt="Annotated live view from the edge camera"
                className={clsx(
                  "absolute inset-0 size-full object-contain",
                  feed.state === "connecting" && "invisible",
                )}
                onLoad={feed.onLoad}
                onError={feed.onError}
              />
            )}
            {feed.state === "connecting" && (
              <p className="hud-title absolute inset-0 grid animate-pulse place-items-center">
                Connecting to edge…
              </p>
            )}
            {feed.state === "offline" && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-1.5 bg-[repeating-linear-gradient(0deg,rgb(111_242_166/0.035)_0_1px,transparent_1px_3px)] p-4 text-center">
                <span className="font-display text-sm font-bold tracking-[0.3em] text-critical uppercase">
                  Camera offline
                </span>
                <span className="text-xs text-fg-muted">
                  {feed.fault === "no-frames"
                    ? "The edge node is sending no frames."
                    : "The edge node's preview is unreachable."}
                </span>
                <span className="max-w-full truncate font-mono text-[10px] text-fg-dim" title={url}>
                  {url}
                </span>
                <div className="mt-1 flex items-center gap-2">
                  <span className="font-mono text-[11px] text-fg-muted">
                    Retrying every 3 s · attempt {feed.attempt + 1}
                  </span>
                  <button type="button" className="btn-ghost" onClick={feed.reconnect}>
                    Retry now
                  </button>
                </div>
              </div>
            )}
          </div>
        ) : (
          <p className="flex flex-1 items-center justify-center px-3 py-4 text-center text-xs text-fg-dim">
            Feed hidden. The stream is closed until you expand it.
          </p>
        )}
      </div>
      {siteId !== undefined && <PhoneCameras siteId={siteId} />}
    </Panel>
  );
}
