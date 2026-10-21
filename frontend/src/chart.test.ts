import { describe, expect, it } from "vitest";

import { layoutChart, niceStep, periodReturns } from "./calc";
import { axisMoney, day } from "./format";

const series = [
  { date: "2026-10-20", value: "1000000.0000", benchmark_value: "1000000.0000" },
  { date: "2026-10-21", value: "1012000.0000", benchmark_value: "1004000.0000" },
  { date: "2026-10-22", value: "996000.0000", benchmark_value: "1008000.0000" },
];

describe("value chart", () => {
  it("picks round steps", () => {
    expect(niceStep(16000)).toBe(5000);
    expect(niceStep(10000)).toBe(2500);
    expect(niceStep(400)).toBe(100);
  });

  it("puts both lines on one axis covering every value", () => {
    const chart = layoutChart(series, 600, 200);
    expect(chart.points.map((p) => p.x)).toEqual([0, 300, 600]);
    const top = chart.ticks[chart.ticks.length - 1].value;
    expect(chart.ticks[0].value).toBeLessThanOrEqual(996000);
    expect(top).toBeGreaterThanOrEqual(1012000);
    for (const p of chart.points) {
      expect(p.y).toBeGreaterThanOrEqual(0);
      expect(p.y).toBeLessThanOrEqual(200);
    }
  });

  it("gives a flat all-cash line a visible range", () => {
    const flat = [series[0], { ...series[0], date: "2026-10-21" }];
    const chart = layoutChart(flat, 600, 200);
    expect(chart.ticks.length).toBeGreaterThan(1);
    expect(chart.points[0].y).toBeGreaterThan(0);
    expect(chart.points[0].y).toBeLessThan(200);
  });

  it("handles a missing benchmark and a single point", () => {
    const chart = layoutChart([{ ...series[0], benchmark_value: null }], 600, 200);
    expect(chart.points[0]).toMatchObject({ x: 300, benchmarkY: null });
  });

  it("compares returns over the period", () => {
    const r = periodReturns(series);
    expect(r.portfolio).toBeCloseTo(-0.004);
    expect(r.benchmark).toBeCloseTo(0.008);
    expect(periodReturns([]).benchmark).toBeNull();
  });

  it("formats axis labels and days", () => {
    expect(axisMoney(1005000, 5000)).toBe("$1.005M");
    expect(axisMoney(1050000, 50000)).toBe("$1.05M");
    expect(axisMoney(1000000, 250000)).toBe("$1.00M");
    expect(day("2026-10-21")).toBe("Oct 21");
  });
});
