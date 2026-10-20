import { useState } from "react";

import type { AgentRunSummary, RunStatus } from "../api";
import { duration, money, quantity, when } from "../format";
import type { Loaded } from "../useDashboard";
import { OrderStatusPill, SidePill } from "./Orders";
import { RichText } from "./RichText";
import { Section } from "./Section";
import { Transcript } from "./Transcript";

const STATUS_CLASS: Record<RunStatus, string> = {
  COMPLETED: "pill-up",
  FAILED: "pill-down",
  SKIPPED: "pill-muted",
  RUNNING: "pill-warn",
};

export function AgentRuns({ portfolioId, runs }: { portfolioId: string; runs: Loaded<AgentRunSummary[]> }) {
  return (
    <Section
      title="AI decisions"
      aside={runs.data && <span className="muted">{runs.data.length} runs</span>}
      state={runs}
    >
      {(list) =>
        list.length === 0 ? (
          <p className="muted">The AI hasn't run on this portfolio yet.</p>
        ) : (
          <ol className="runs">
            {list.map((run) => (
              <Run key={run.id} portfolioId={portfolioId} run={run} />
            ))}
          </ol>
        )
      }
    </Section>
  );
}

function Run({ portfolioId, run }: { portfolioId: string; run: AgentRunSummary }) {
  const [showTranscript, setShowTranscript] = useState(false);
  const filled = run.decisions.filter((d) => d.order?.status === "FILLED").length;
  return (
    <li className="run">
      <div className="run-head">
        <span className={`pill ${STATUS_CLASS[run.status]}`}>{run.status}</span>
        <strong>{when(run.started_at)}</strong>
        <span className="muted">
          {[
            duration(run.started_at, run.finished_at),
            run.model_id,
            run.prompt_version && `prompt ${run.prompt_version}`,
            run.input_tokens + run.output_tokens > 0 &&
              `${(run.input_tokens / 1000).toFixed(1)}K in / ${(run.output_tokens / 1000).toFixed(1)}K out tokens`,
            run.run_key,
          ]
            .filter(Boolean)
            .join(" · ")}
        </span>
      </div>

      {run.error && <p className="notice error">{run.error}</p>}
      {run.summary && <RichText text={run.summary} />}

      {run.decisions.length > 0 && (
        <>
          <p className="muted small">
            {run.decisions.length} proposals · {filled} filled · {run.decisions.length - filled} not filled
          </p>
          <ul className="decisions">
            {run.decisions.map((d) => (
              <li key={d.sequence} className="decision">
                <div className="decision-head">
                  <SidePill side={d.side} />
                  <span className="symbol">{d.symbol}</span>
                  <span>{quantity(d.quantity)} shares</span>
                  {d.order && <OrderStatusPill order={d.order} />}
                  {d.order?.execution && (
                    <span className="muted">
                      @ {money(d.order.execution.price)} = {money(d.order.execution.gross_amount)}
                    </span>
                  )}
                </div>
                <div className="rationale">
                  <RichText text={d.rationale} />
                </div>
                {d.order?.rejection_reason && <p className="down small">Risk engine: {d.order.rejection_reason}</p>}
              </li>
            ))}
          </ul>
        </>
      )}

      {run.status !== "SKIPPED" && (
        <button className="link" onClick={() => setShowTranscript(!showTranscript)}>
          {showTranscript ? "Hide" : "Show"} what the AI saw and did
        </button>
      )}
      {showTranscript && <Transcript portfolioId={portfolioId} runId={run.id} />}
    </li>
  );
}
