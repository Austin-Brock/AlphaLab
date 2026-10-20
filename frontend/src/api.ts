// Types mirror backend/app/schemas.py. Money and quantities arrive as decimal strings.

export type Side = "BUY" | "SELL";
export type OrderStatus = "PENDING" | "FILLED" | "REJECTED";
export type RunStatus = "RUNNING" | "COMPLETED" | "FAILED" | "SKIPPED";

export interface Portfolio {
  id: string;
  name: string;
  starting_capital: string;
  strategy_id: string;
  status: "ACTIVE" | "PAUSED" | "CLOSED";
  max_position_pct: string;
  min_cash_pct: string;
  created_at: string;
}

export interface PositionValuation {
  symbol: string;
  quantity: string;
  average_cost: string;
  price: string;
  priced_at_cost: boolean;
  market_value: string;
}

export interface PortfolioValue {
  portfolio_id: string;
  cash: string;
  positions_value: string;
  total_value: string;
  positions: PositionValuation[];
}

export interface RiskCheck {
  check_name: string;
  passed: boolean;
  message: string;
}

export interface Execution {
  id: string;
  order_id: string;
  symbol: string;
  side: Side;
  quantity: string;
  price: string;
  market_price: string;
  gross_amount: string;
  commission: string;
  executed_at: string;
}

export interface Order {
  id: string;
  portfolio_id: string;
  client_order_id: string;
  symbol: string;
  side: Side;
  quantity: string;
  status: OrderStatus;
  source: string;
  reference_price: string | null;
  rejection_reason: string | null;
  created_at: string;
  risk_checks: RiskCheck[];
  execution: Execution | null;
}

export interface AgentDecision {
  sequence: number;
  symbol: string;
  side: Side;
  quantity: string;
  rationale: string;
  order: Order | null;
}

export interface AgentRunSummary {
  id: string;
  portfolio_id: string;
  strategy_id: string;
  run_key: string | null;
  status: RunStatus;
  model_id: string | null;
  prompt_version: string | null;
  summary: string | null;
  error: string | null;
  input_tokens: number;
  output_tokens: number;
  started_at: string;
  finished_at: string | null;
  decisions: AgentDecision[];
}

// Bedrock Converse content blocks, as stored in the run transcript.
export interface ContentBlock {
  text?: string;
  reasoningContent?: { reasoningText?: { text: string } };
  toolUse?: { toolUseId: string; name: string; input: unknown };
  toolResult?: { toolUseId: string; content: { json?: unknown; text?: string }[] };
}

export interface TranscriptMessage {
  role: "user" | "assistant";
  content: ContentBlock[];
}

export interface AgentRun extends AgentRunSummary {
  input_snapshot: Record<string, unknown>;
  transcript: TranscriptMessage[] | null;
}

export interface MarketClock {
  is_open: boolean;
  next_open: string;
  next_close: string;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

// The dashboard only reads. It never places orders or starts agent runs.
async function get<T>(path: string): Promise<T> {
  const response = await fetch(`/api${path}`);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      // Not JSON (e.g. the backend isn't running and the proxy answered).
    }
    throw new ApiError(response.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return response.json() as Promise<T>;
}

export const api = {
  portfolios: () => get<Portfolio[]>("/portfolios"),
  value: (id: string) => get<PortfolioValue>(`/portfolios/${id}/value`),
  orders: (id: string) => get<Order[]>(`/portfolios/${id}/orders`),
  agentRuns: (id: string) => get<AgentRunSummary[]>(`/portfolios/${id}/agent-runs`),
  agentRun: (id: string, runId: string) => get<AgentRun>(`/portfolios/${id}/agent-runs/${runId}`),
  clock: () => get<MarketClock>("/market/clock"),
};
