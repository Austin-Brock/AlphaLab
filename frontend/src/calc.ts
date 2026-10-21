import type { PortfolioValue, PositionValuation, ValuePoint } from "./api";

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

export interface ChartPoint {
  date: string;
  value: number;
  benchmark: number | null;
  x: number;
  y: number;
  benchmarkY: number | null;
}

export interface Chart {
  points: ChartPoint[];
  ticks: { value: number; y: number }[];
  step: number;
}

/** A round step (1, 2, 2.5 or 5 × 10ⁿ) that splits `span` into about `parts` pieces. */
export function niceStep(span: number, parts = 4): number {
  const raw = span / parts;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const nice = [1, 2, 2.5, 5, 10].find((m) => m * magnitude >= raw) ?? 10;
  return nice * magnitude;
}

/** Pixel positions for the value chart. Both lines share one y-axis so they compare directly. */
export function layoutChart(series: ValuePoint[], width: number, height: number): Chart {
  const values = series.flatMap((p) => [Number(p.value), ...(p.benchmark_value ? [Number(p.benchmark_value)] : [])]);
  let low = Math.min(...values);
  let high = Math.max(...values);
  // A flat line (e.g. all cash) still gets a visible range of about ±0.5%, centered.
  const minSpan = high * 0.01;
  if (high - low < minSpan) {
    const mid = (high + low) / 2;
    [low, high] = [mid - minSpan / 2, mid + minSpan / 2];
  }
  const step = niceStep(high - low);
  const min = Math.floor(low / step) * step;
  const max = Math.max(Math.ceil(high / step) * step, min + step);
  const y = (v: number) => height - ((v - min) / (max - min)) * height;
  const x = (i: number) => (series.length > 1 ? (i / (series.length - 1)) * width : width / 2);

  const ticks = [];
  for (let v = min; v <= max + step / 2; v += step) ticks.push({ value: v, y: y(v) });

  return {
    step,
    ticks,
    points: series.map((p, i) => {
      const benchmark = p.benchmark_value === null ? null : Number(p.benchmark_value);
      return {
        date: p.date,
        value: Number(p.value),
        benchmark,
        x: x(i),
        y: y(Number(p.value)),
        benchmarkY: benchmark === null ? null : y(benchmark),
      };
    }),
  };
}

/** Return from the first point to the last, for the portfolio and the benchmark. */
export function periodReturns(series: ValuePoint[]): { portfolio: number; benchmark: number | null } {
  const first = series[0];
  const last = series[series.length - 1];
  if (!first || !last) return { portfolio: 0, benchmark: null };
  const portfolio = Number(last.value) / Number(first.value) - 1;
  const benchmark =
    first.benchmark_value && last.benchmark_value
      ? Number(last.benchmark_value) / Number(first.benchmark_value) - 1
      : null;
  return { portfolio, benchmark };
}
