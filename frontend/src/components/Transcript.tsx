import { useEffect, useState } from "react";

import { api, type AgentRun, type ContentBlock } from "../api";
import { RichText } from "./RichText";

/** The full model conversation for one run: reasoning, tool calls, tool results, and replies. */
export function Transcript({ portfolioId, runId }: { portfolioId: string; runId: string }) {
  const [run, setRun] = useState<AgentRun>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    api
      .agentRun(portfolioId, runId)
      .then(setRun)
      .catch((e: Error) => setError(e.message));
  }, [portfolioId, runId]);

  if (error) return <p className="notice error">{error}</p>;
  if (!run) return <p className="muted">Loading transcript…</p>;
  return <TranscriptView run={run} />;
}

export function TranscriptView({ run }: { run: AgentRun }) {
  const toolNames = new Map<string, string>();
  for (const message of run.transcript ?? []) {
    for (const block of message.content) {
      if (block.toolUse) toolNames.set(block.toolUse.toolUseId, block.toolUse.name);
    }
  }

  return (
    <div className="transcript">
      <details>
        <summary>Portfolio snapshot the AI was given</summary>
        <pre>{JSON.stringify(run.input_snapshot, null, 2)}</pre>
      </details>
      {(run.transcript ?? []).map((message, i) =>
        message.content.map((block, j) => (
          <Block key={`${i}-${j}`} role={message.role} block={block} toolNames={toolNames} first={i === 0} />
        )),
      )}
    </div>
  );
}

function Block({
  role,
  block,
  toolNames,
  first,
}: {
  role: "user" | "assistant";
  block: ContentBlock;
  toolNames: Map<string, string>;
  first: boolean;
}) {
  if (block.reasoningContent?.reasoningText) {
    return (
      <details className="turn reasoning">
        <summary>AI reasoning</summary>
        <p>{block.reasoningContent.reasoningText.text}</p>
      </details>
    );
  }
  if (block.toolUse) {
    return (
      <div className="turn tool-call">
        <span className="turn-label">AI called</span>
        <code>
          {block.toolUse.name}({formatArgs(block.toolUse.input)})
        </code>
      </div>
    );
  }
  if (block.toolResult) {
    const body = block.toolResult.content.map((c) => c.json ?? c.text);
    const value = body.length === 1 ? body[0] : body;
    const isError = typeof value === "object" && value !== null && "error" in value;
    return (
      <details className={`turn tool-result ${isError ? "is-error" : ""}`}>
        <summary>
          {isError ? "Refused: " : "Result of "}
          {isError ? String((value as { error: unknown }).error) : toolNames.get(block.toolResult.toolUseId)}
        </summary>
        <pre>{JSON.stringify(value, null, 2)}</pre>
      </details>
    );
  }
  if (block.text) {
    return (
      <div className={`turn ${role === "assistant" ? "ai-text" : "system-text"}`}>
        <span className="turn-label">{role === "assistant" ? "AI" : first ? "Instructions" : "AlphaLab"}</span>
        <RichText text={block.text} />
      </div>
    );
  }
  return null;
}

function formatArgs(input: unknown): string {
  if (!input || typeof input !== "object") return "";
  return Object.entries(input)
    .map(([k, v]) => `${k}: ${JSON.stringify(v)}`)
    .join(", ");
}
