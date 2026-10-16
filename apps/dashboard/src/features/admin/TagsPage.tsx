import type { Tag } from "@pids/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Chip, Panel } from "../../components/ui";
import { pids } from "../../lib/api";
import { useSession } from "../../lib/hooks";

/** Cooperative-tag registry. Revocation takes effect in the decision engine immediately. */
export function TagsPage({ siteId }: { siteId: string }) {
  const session = useSession();
  const isAdmin = session?.user.role === "admin";
  const qc = useQueryClient();
  const tags = useQuery({
    queryKey: ["tags", siteId],
    queryFn: async () => {
      const { data } = await pids.api.GET("/api/v1/sites/{site_id}/tags", {
        params: { path: { site_id: siteId } },
      });
      return data ?? [];
    },
  });
  const toggle = useMutation({
    mutationFn: async (tag: Tag) => {
      const { data, response } = await pids.api.PATCH("/api/v1/sites/{site_id}/tags/{tag_id}", {
        params: { path: { site_id: siteId, tag_id: tag.id } },
        body: { authorized: !tag.authorized },
      });
      if (!data) throw new Error(`Update failed (${String(response.status)})`);
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tags", siteId] }),
  });

  return (
    <Panel
      title="Cooperative tag registry"
      right={
        <span className="text-[11px] text-fg-dim">Identity without biometrics · ADR-0005</span>
      }
      className="flex-1"
    >
      <table className="w-full text-left text-[13px]">
        <thead className="hud-title border-b border-line">
          <tr>
            {["Tag", "Label", "Kind", "Home zone", "Status", ""].map((h) => (
              <th key={h} className="px-4 py-2 font-semibold">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {(tags.data ?? []).map((t) => (
            <tr key={t.id} className="border-b border-line hover:bg-ink-800">
              <td className="px-4 py-2 font-mono text-[12px]">{t.id}</td>
              <td className="px-4 py-2">{t.label}</td>
              <td className="px-4 py-2 text-fg-muted">{t.kind}</td>
              <td className="px-4 py-2 text-fg-muted">{t.home_zone ?? "—"}</td>
              <td className="px-4 py-2">
                {t.authorized ? (
                  <Chip tone="var(--color-phosphor)">Authorised</Chip>
                ) : (
                  <Chip tone="var(--color-critical)">Revoked</Chip>
                )}
              </td>
              <td className="px-4 py-2 text-right">
                {isAdmin && (
                  <button
                    type="button"
                    className={t.authorized ? "btn-danger" : "btn-primary"}
                    disabled={toggle.isPending}
                    onClick={() => {
                      toggle.mutate(t);
                    }}
                  >
                    {t.authorized ? "Revoke" : "Authorise"}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!isAdmin && (
        <p className="p-4 text-xs text-fg-dim">Only administrators can change tag authorisation.</p>
      )}
      {toggle.isError && <p className="p-4 text-xs text-critical">{toggle.error.message}</p>}
    </Panel>
  );
}
