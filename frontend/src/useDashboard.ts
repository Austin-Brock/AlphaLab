import { useCallback, useEffect, useState } from "react";

import {
  api,
  type AgentRunSummary,
  type MarketClock,
  type Order,
  type PortfolioValue,
  type StatusChange,
  type ValueHistory,
} from "./api";

export const REFRESH_SECONDS = 30;

export interface Loaded<T> {
  data?: T;
  error?: string;
}

export interface DashboardData {
  value: Loaded<PortfolioValue>;
  history: Loaded<ValueHistory>;
  orders: Loaded<Order[]>;
  runs: Loaded<AgentRunSummary[]>;
  clock: Loaded<MarketClock>;
  statusChanges: Loaded<StatusChange[]>;
  updatedAt?: Date;
  loading: boolean;
}

const EMPTY: DashboardData = {
  value: {},
  history: {},
  orders: {},
  runs: {},
  clock: {},
  statusChanges: {},
  loading: true,
};

function settle<T>(result: PromiseSettledResult<T>): Loaded<T> {
  return result.status === "fulfilled"
    ? { data: result.value }
    : { error: result.reason instanceof Error ? result.reason.message : String(result.reason) };
}

/** Loads everything for one portfolio and refreshes it periodically. Each section fails on its own. */
export function useDashboard(portfolioId: string | undefined) {
  const [state, setState] = useState<DashboardData>(EMPTY);

  const refresh = useCallback(async () => {
    if (!portfolioId) return;
    setState((s) => ({ ...s, loading: true }));
    const [value, history, orders, runs, clock, statusChanges] = await Promise.allSettled([
      api.value(portfolioId),
      api.valueHistory(portfolioId),
      api.orders(portfolioId),
      api.agentRuns(portfolioId),
      api.clock(),
      api.statusChanges(portfolioId),
    ]);
    setState({
      value: settle(value),
      history: settle(history),
      orders: settle(orders),
      runs: settle(runs),
      clock: settle(clock),
      statusChanges: settle(statusChanges),
      updatedAt: new Date(),
      loading: false,
    });
  }, [portfolioId]);

  useEffect(() => {
    setState(EMPTY);
    void refresh();
    const timer = window.setInterval(() => void refresh(), REFRESH_SECONDS * 1000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  return { ...state, refresh };
}
