import type { Portfolio, PortfolioValue } from "../api";
import { overview, positionRows } from "../calc";
import { money, percent, signedMoney, tone, when } from "../format";
import type { Loaded } from "../useDashboard";
import { Section } from "./Section";

const PALETTE = ["#2563eb", "#7c3aed", "#0891b2", "#db2777", "#ea580c", "#16a34a", "#ca8a04", "#4f46e5", "#0d9488", "#be123c"];

export function Overview({ portfolio, value }: { portfolio: Portfolio; value: Loaded<PortfolioValue> }) {
  return (
    <Section
      title={portfolio.name}
      aside={
        <div className="meta">
          <span className={`pill ${portfolio.status === "ACTIVE" ? "pill-up" : "pill-warn"}`}>{portfolio.status}</span>
          <span>{portfolio.strategy_id}</span>
          <span>Started {when(portfolio.created_at)}</span>
        </div>
      }
      state={value}
    >
      {(v) => {
        const o = overview(v, portfolio.starting_capital);
        const rows = positionRows(v.positions, o.totalValue);
        return (
          <>
            <div className="stats">
              <Stat label="Portfolio value" value={money(o.totalValue)} big />
              <Stat
                label="Total return"
                value={signedMoney(o.pnl)}
                detail={percent(o.pnlPct, { signed: true })}
                tone={tone(o.pnl)}
              />
              <Stat label="Cash" value={money(o.cash)} detail={`${percent(o.cashWeight, { digits: 1 })} of portfolio`} />
              <Stat label="Invested" value={money(o.invested)} detail={`${rows.length} ${rows.length === 1 ? "position" : "positions"}`} />
              <Stat label="Starting capital" value={money(o.startingCapital, { whole: true })} />
            </div>

            <div className="allocation" aria-label="Allocation">
              {rows.map((r, i) => (
                <span
                  key={r.symbol}
                  style={{ width: `${r.weight * 100}%`, background: PALETTE[i % PALETTE.length] }}
                  title={`${r.symbol} ${percent(r.weight, { digits: 1 })}`}
                />
              ))}
              <span className="cash" style={{ width: `${o.cashWeight * 100}%` }} title={`Cash ${percent(o.cashWeight, { digits: 1 })}`} />
            </div>
            <div className="legend">
              {rows.map((r, i) => (
                <span key={r.symbol}>
                  <i style={{ background: PALETTE[i % PALETTE.length] }} /> {r.symbol} {percent(r.weight, { digits: 1 })}
                </span>
              ))}
              <span>
                <i className="cash" /> Cash {percent(o.cashWeight, { digits: 1 })}
              </span>
              <span className="muted">
                Limits: {percent(Number(portfolio.max_position_pct), { digits: 0 })} max per stock ·{" "}
                {percent(Number(portfolio.min_cash_pct), { digits: 0 })} min cash
              </span>
            </div>
          </>
        );
      }}
    </Section>
  );
}

function Stat({ label, value, detail, tone, big }: { label: string; value: string; detail?: string; tone?: string; big?: boolean }) {
  return (
    <div className={`stat ${big ? "stat-big" : ""}`}>
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${tone ?? ""}`}>{value}</div>
      {detail && <div className={`stat-detail ${tone ?? ""}`}>{detail}</div>}
    </div>
  );
}
