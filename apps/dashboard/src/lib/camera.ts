/** The edge node serves its preview on loopback only (ADR-0011). */
export const DEFAULT_PREVIEW_URL = "http://127.0.0.1:8090/stream.mjpg";

/** The configured preview URL, falling back to the edge's default when unset or blank. */
export function previewUrl(configured: string | undefined): string {
  return configured?.trim() || DEFAULT_PREVIEW_URL;
}

export const EDGE_PREVIEW_URL = previewUrl(import.meta.env.VITE_EDGE_PREVIEW_URL);

/**
 * The stream URL for one connection attempt. Every reconnect gets a distinct URL so the
 * browser cannot answer it with the frozen last frame it already holds for the old one;
 * the edge ignores the query string.
 */
export function attemptUrl(url: string, attempt: number): string {
  if (attempt === 0) return url;
  return `${url}${url.includes("?") ? "&" : "?"}attempt=${attempt}`;
}

/**
 * The edge's single-frame endpoint beside its stream, used as a liveness probe; `null`
 * when the URL is not an edge stream. Probing is needed because browsers fire no event
 * when an MJPEG stream dies mid-way: the <img> just freezes on its last frame.
 */
export function snapshotUrl(url: string): string | null {
  try {
    const u = new URL(url);
    if (!u.pathname.endsWith("/stream.mjpg")) return null;
    u.pathname = u.pathname.replace(/stream\.mjpg$/, "snapshot.jpg");
    u.search = "";
    return u.toString();
  } catch {
    return null;
  }
}
