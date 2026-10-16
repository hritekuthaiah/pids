import { useQuery } from "@tanstack/react-query";

import { Chip, LevelBadge, Panel } from "../../components/ui";
import { pids } from "../../lib/api";
import { entityLabel, humanize } from "../../lib/format";

const STATUS_TONE: Record<string, string> = {
  open: "var(--color-critical)",
  acknowledged: "var(--color-elevated)",
  resolved: "var(--color-phosphor)",
  false_alarm: "var(--color-fg-dim)",
};

/** Every alert raised at the site, for shift hand-over and incident review. */
export function AlertsLogPage({ siteId }: { siteId: string }) {
  const log = useQuery({
    queryKey: ["alerts-log", siteId],
    refetchInterval: 10_000,
    queryFn: async () => {
      const { data } = await pids.api.GET("/api/v1/alerts", {
        params: { query: { site_id: siteId, limit: 300 } },
      });
      return data ?? [];
    },
  });
  const rows = [...(log.data ?? [])].sort((a, b) => b.opened_at.localeCompare(a.opened_at));
  const falseAlarms = rows.filter((r) => r.status === "false_alarm").length;
  return (
    <Panel
      title="Alert log"
      right={
        <span className="font-mono text-[11px] text-fg-muted">
          {rows.length} alerts · {falseAlarms} marked false alarm
        </span>
      }
      className="flex-1"
    >
      <div className="min-h-0 flex-1 overflow-y-auto">
        <table className="w-full text-left text-[13px]">
          <thead className="hud-title sticky top-0 border-b border-line bg-ink-850">
            <tr>
              {["Opened", "Level", "Class", "Zone", "Entity", "Score", "Status", "Note"].map(
                (h) => (
                  <th key={h} className="px-3 py-2 font-semibold">
                    {h}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.id} className="border-b border-line hover:bg-ink-800">
                <td className="px-3 py-1.5 font-mono text-[11.5px] text-fg-muted">
                  {new Date(a.opened_at).toLocaleString("en-GB", { hour12: false })}
                </td>
                <td className="px-3 py-1.5">
                  <LevelBadge level={a.max_level} />
                </td>
                <td className="px-3 py-1.5">{a.entity_class}</td>
                <td className="px-3 py-1.5 text-fg-muted">{humanize(a.zone_id)}</td>
                <td className="px-3 py-1.5 font-mono text-[11.5px] text-fg-dim">
                  {entityLabel(a.entity_id)}
                </td>
                <td className="px-3 py-1.5 font-mono">{a.score}</td>
                <td className="px-3 py-1.5">
                  <Chip tone={STATUS_TONE[a.status]}>{a.status.replace("_", " ")}</Chip>
                </td>
                <td className="max-w-64 truncate px-3 py-1.5 text-fg-muted">
                  {a.resolution_note ?? ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
