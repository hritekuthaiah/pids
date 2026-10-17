import { useQuery } from "@tanstack/react-query";

import { pids } from "../../lib/api";

/**
 * Phones currently offering their camera to the site (ADR-0013). The console only lists
 * them: the stream stays on the local network, and the edge node is what consumes it.
 */
export function PhoneCameras({ siteId }: { siteId: string }) {
  const { data } = useQuery({
    queryKey: ["phone-cameras", siteId],
    refetchInterval: 15_000,
    queryFn: async () => {
      const { data } = await pids.api.GET("/api/v1/sites/{site_id}/cameras", {
        params: { path: { site_id: siteId } },
      });
      return data ?? [];
    },
  });
  if (!data || data.length === 0) return null;
  return (
    <div className="border-t border-line px-3 py-2">
      <span className="hud-title">Phone cameras offered</span>
      <ul className="mt-1 flex flex-col gap-0.5">
        {data.map((c) => (
          <li key={c.url} className="flex items-baseline gap-2 text-[11.5px]">
            <span className="text-fg-muted">{c.name}</span>
            <code className="font-mono text-[11px] text-phosphor">{c.url}</code>
            <span className="ml-auto font-mono text-[10px] text-fg-dim">
              {c.width}×{c.height} · {Math.round(c.fps)} fps
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-1 text-[10.5px] text-fg-dim">
        Point the edge node at one: <code className="font-mono">make edge SOURCE=…</code>
      </p>
    </div>
  );
}
