import { type PointerEvent, useEffect, useRef, useState } from "react";

import type { ValueHistory } from "../api";
import { layoutChart, periodReturns } from "../calc";
import { axisMoney, day, money, percent, tone } from "../format";
import type { Loaded } from "../useDashboard";
import { Section } from "./Section";

const HEIGHT = 240;
const MARGIN = { top: 10, right: 12, bottom: 26, left: 64 };

/** Width of an element, kept up to date as the page resizes, so the SVG draws at real pixels. */
function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

export function ValueChart({ history }: { history: Loaded<ValueHistory> }) {
  return (
    <Section title="Value over time" state={history}>
      {(h) => <Chart history={h} />}
    </Section>
  );
}

function Chart({ history }: { history: ValueHistory }) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState<number>();
  const series = history.points;
  const returns = periodReturns(series);

  if (series.length < 2) {
    return (
      <p className="muted">
        The chart fills in after the portfolio's first trading day closes, with {history.benchmark} alongside for
        comparison.
      </p>
    );
  }

  const innerWidth = Math.max(width - MARGIN.left - MARGIN.right, 0);
  const innerHeight = HEIGHT - MARGIN.top - MARGIN.bottom;
  const chart = layoutChart(series, innerWidth, innerHeight);
  const line = (pts: { x: number; y: number }[]) => pts.map((p, i) => `${i ? "L" : "M"}${p.x},${p.y}`).join("");
  const benchmarkLine = chart.points.flatMap((p) => (p.benchmarkY === null ? [] : [{ x: p.x, y: p.benchmarkY }]));
  const labelIndexes = [...new Set([0, Math.floor((series.length - 1) / 2), series.length - 1])];
  const active = hover === undefined ? undefined : chart.points[hover];

  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const x = e.clientX - e.currentTarget.getBoundingClientRect().left - MARGIN.left;
    const step = innerWidth / (series.length - 1);
    setHover(Math.min(series.length - 1, Math.max(0, Math.round(x / step))));
  };

  return (
    <>
      <div className="chart-legend">
        <span>
          <i className="swatch-portfolio" /> This portfolio{" "}
          <strong className={tone(returns.portfolio)}>{percent(returns.portfolio, { signed: true })}</strong>
        </span>
        {returns.benchmark !== null && (
          <span>
            <i className="swatch-benchmark" /> Same money in {history.benchmark}{" "}
            <strong className={tone(returns.benchmark)}>{percent(returns.benchmark, { signed: true })}</strong>
          </span>
        )}
        <span className="muted">Daily closes since {day(series[0].date)}</span>
      </div>

      <div className="chart" ref={ref}>
        {width > 0 && (
          <svg
            width={width}
            height={HEIGHT}
            role="img"
            aria-label={`Portfolio value from ${day(series[0].date)} to ${day(series[series.length - 1].date)}`}
            onPointerMove={onMove}
            onPointerLeave={() => setHover(undefined)}
          >
            <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
              {chart.ticks.map((t) => (
                <g key={t.value}>
                  <line className="chart-grid" x1={0} x2={innerWidth} y1={t.y} y2={t.y} />
                  <text className="chart-axis" x={-8} y={t.y} textAnchor="end" dominantBaseline="middle">
                    {axisMoney(t.value, chart.step)}
                  </text>
                </g>
              ))}
              {labelIndexes.map((i) => (
                <text
                  key={i}
                  className="chart-axis"
                  x={chart.points[i].x}
                  y={innerHeight + 18}
                  textAnchor={i === 0 ? "start" : i === series.length - 1 ? "end" : "middle"}
                >
                  {day(series[i].date)}
                </text>
              ))}
              {benchmarkLine.length > 1 && <path className="chart-benchmark" d={line(benchmarkLine)} />}
              <path className="chart-portfolio" d={line(chart.points)} />
              {active && (
                <g>
                  <line className="chart-cursor" x1={active.x} x2={active.x} y1={0} y2={innerHeight} />
                  {active.benchmarkY !== null && (
                    <circle className="chart-dot-benchmark" cx={active.x} cy={active.benchmarkY} r={3.5} />
                  )}
                  <circle className="chart-dot" cx={active.x} cy={active.y} r={4} />
                </g>
              )}
            </g>
          </svg>
        )}
        {active && (
          <div
            className="chart-tip"
            style={{
              left: Math.min(Math.max(MARGIN.left + active.x, 80), width - 80),
            }}
          >
            <div className="muted">{day(active.date)}</div>
            <div>
              <i className="swatch-portfolio" /> {money(active.value)}
            </div>
            {active.benchmark !== null && (
              <div>
                <i className="swatch-benchmark" /> {money(active.benchmark)}
              </div>
            )}
          </div>
        )}
      </div>
      {history.stale && <p className="muted small">Market data is temporarily unavailable; some prices may be out of date.</p>}
    </>
  );
}
