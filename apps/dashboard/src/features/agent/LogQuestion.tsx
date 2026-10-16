import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { Chip, LevelBadge } from "../../components/ui";
import { errorMessage, filterChips, type LogAnswer } from "../../lib/agent";
import { pids } from "../../lib/api";
import { humanize } from "../../lib/format";

/** Ask the alert log a question in plain language; the server answers from the records. */
export function LogQuestion({ siteId }: { siteId: string }) {
  const [question, setQuestion] = useState("");
  const ask = useMutation({
    mutationFn: async (q: string): Promise<LogAnswer> => {
      const { data, error } = await pids.api.POST("/api/v1/agent/query", {
        body: { site_id: siteId, question: q },
      });
      if (!data) throw new Error(errorMessage(error, "query failed"));
      return data;
    },
  });
  return (
    <div className="flex flex-col gap-2 border-b border-line p-3">
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (question.trim().length >= 3) ask.mutate(question.trim());
        }}
      >
        <input
          aria-label="Ask the log"
          className="field flex-1"
          placeholder="Ask the log — e.g. “critical alerts in the secure core today”"
          value={question}
          maxLength={500}
          onChange={(e) => {
            setQuestion(e.target.value);
          }}
        />
        <button
          type="submit"
          className="btn-primary"
          disabled={ask.isPending || question.trim().length < 3}
        >
          {ask.isPending ? "Asking…" : "Ask"}
        </button>
      </form>
      {ask.isError && (
        <p className="text-[12px] text-[var(--color-critical)]">{ask.error.message}</p>
      )}
      {ask.data && <LogAnswerView answer={ask.data} />}
    </div>
  );
}

export function LogAnswerView({ answer }: { answer: LogAnswer }) {
  return (
    <div className="flex flex-col gap-1.5 text-[12.5px]">
      <p className="font-semibold text-fg">{answer.answer}</p>
      <div className="flex flex-wrap items-center gap-1">
        <span className="hud-title mr-1">Understood as</span>
        {filterChips(answer.interpreted).map((c) => (
          <Chip key={c}>{c}</Chip>
        ))}
      </div>
      {answer.alerts.length > 0 && (
        <ul className="flex flex-col gap-0.5">
          {answer.alerts.map((a) => (
            <li key={a.id} className="flex items-center gap-2 text-fg-muted">
              <LevelBadge level={a.level} />
              <span className="font-mono text-[11px]">
                {new Date(a.opened_at).toLocaleString("en-GB", { hour12: false })}
              </span>
              <span>
                {a.entity_class} · {humanize(a.zone_id)} · {a.status.replace("_", " ")}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
