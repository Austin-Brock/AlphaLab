import type { PortfolioValue, PositionValuation } from "./api";

export interface PositionRow {
  symbol: string;
  quantity: number;
  averageCost: number;
  price: number;
  pricedAtCost: boolean;
  marketValue: number;
  costBasis: number;
  unrealizedPnl: number;
  unrealizedPct: number;
  weight: number;
}

export interface Overview {
  totalValue: number;
  cash: number;
  invested: number;
  startingCapital: number;
  pnl: number;
  pnlPct: number;
  cashWeight: number;
}

export function overview(value: PortfolioValue, startingCapital: string): Overview {
  const totalValue = Number(value.total_value);
  const cash = Number(value.cash);
  const start = Number(startingCapital);
  const pnl = totalValue - start;
  return {
    totalValue,
    cash,
    invested: Number(value.positions_value),
    startingCapital: start,
    pnl,
    pnlPct: start > 0 ? pnl / start : 0,
    cashWeight: totalValue > 0 ? cash / totalValue : 0,
  };
}

/** Holdings with unrealized P&L and portfolio weight, largest position first. */
export function positionRows(positions: PositionValuation[], totalValue: number): PositionRow[] {
  return positions
    .map((p) => {
      const quantity = Number(p.quantity);
      const averageCost = Number(p.average_cost);
      const marketValue = Number(p.market_value);
      const costBasis = quantity * averageCost;
      const unrealizedPnl = marketValue - costBasis;
      return {
        symbol: p.symbol,
        quantity,
        averageCost,
        price: Number(p.price),
        pricedAtCost: p.priced_at_cost,
        marketValue,
        costBasis,
        unrealizedPnl,
        unrealizedPct: costBasis > 0 ? unrealizedPnl / costBasis : 0,
        weight: totalValue > 0 ? marketValue / totalValue : 0,
      };
    })
    .sort((a, b) => b.marketValue - a.marketValue);
}
