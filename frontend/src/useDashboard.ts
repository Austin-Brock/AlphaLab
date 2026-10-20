import { useCallback, useEffect, useState } from "react";

import { api, type AgentRunSummary, type MarketClock, type Order, type PortfolioValue } from "./api";

export const REFRESH_SECONDS = 30;

export interface Loaded<T> {
  data?: T;
  error?: string;
}

export interface DashboardData {
  value: Loaded<PortfolioValue>;
  orders: Loaded<Order[]>;
  runs: Loaded<AgentRunSummary[]>;
  clock: Loaded<MarketClock>;
  updatedAt?: Date;
  loading: boolean;
}

function settle<T>(result: PromiseSettledResult<T>): Loaded<T> {
  return result.status === "fulfilled"
    ? { data: result.value }
    : { error: result.reason instanceof Error ? result.reason.message : String(result.reason) };
}

/** Loads everything for one portfolio and refreshes it periodically. Each section fails on its own. */
export function useDashboard(portfolioId: string | undefined) {
  const [state, setState] = useState<DashboardData>({
    value: {},
    orders: {},
    runs: {},
    clock: {},
    loading: true,
  });

  const refresh = useCallback(async () => {
    if (!portfolioId) return;
    setState((s) => ({ ...s, loading: true }));
    const [value, orders, runs, clock] = await Promise.allSettled([
      api.value(portfolioId),
      api.orders(portfolioId),
      api.agentRuns(portfolioId),
      api.clock(),
    ]);
    setState({
      value: settle(value),
      orders: settle(orders),
      runs: settle(runs),
      clock: settle(clock),
      updatedAt: new Date(),
      loading: false,
    });
  }, [portfolioId]);

  useEffect(() => {
    setState({ value: {}, orders: {}, runs: {}, clock: {}, loading: true });
    void refresh();
    const timer = window.setInterval(() => void refresh(), REFRESH_SECONDS * 1000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  return { ...state, refresh };
}
