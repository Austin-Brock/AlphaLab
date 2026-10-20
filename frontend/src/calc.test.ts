import { describe, expect, it } from "vitest";

import { overview, positionRows } from "./calc";
import { percent, signedMoney } from "./format";

const value = {
  portfolio_id: "p",
  cash: "500000.0000",
  positions_value: "510000.0000",
  total_value: "1010000.0000",
  positions: [
    {
      symbol: "AAPL",
      quantity: "100.000000",
      average_cost: "100.0000",
      price: "110.0000",
      priced_at_cost: false,
      market_value: "11000.0000",
    },
    {
      symbol: "MSFT",
      quantity: "1000.000000",
      average_cost: "500.0000",
      price: "499.0000",
      priced_at_cost: false,
      market_value: "499000.0000",
    },
  ],
};

describe("overview", () => {
  it("measures profit against starting capital", () => {
    const o = overview(value, "1000000.0000");
    expect(o.pnl).toBe(10000);
    expect(o.pnlPct).toBeCloseTo(0.01);
    expect(o.cashWeight).toBeCloseTo(500000 / 1010000);
  });
});

describe("positionRows", () => {
  it("computes unrealized P&L and weight, largest first", () => {
    const [msft, aapl] = positionRows(value.positions, 1010000);
    expect(msft.symbol).toBe("MSFT");
    expect(msft.unrealizedPnl).toBe(-1000);
    expect(aapl.unrealizedPnl).toBe(1000);
    expect(aapl.unrealizedPct).toBeCloseTo(0.1);
    expect(aapl.weight).toBeCloseTo(11000 / 1010000);
  });
});

describe("format", () => {
  it("signs money and percentages", () => {
    expect(signedMoney(1234.5)).toBe("+$1,234.50");
    expect(signedMoney(-2)).toBe("−$2.00");
    expect(percent(0.0123, { signed: true })).toBe("+1.23%");
    expect(percent(-0.05, { signed: true })).toBe("−5.00%");
    expect(percent(-0.0000171, { signed: true })).toBe("0.00%");
  });
});
