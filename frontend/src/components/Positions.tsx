import type { PortfolioValue } from "../api";
import { positionRows } from "../calc";
import { money, percent, quantity, signedMoney, tone } from "../format";
import type { Loaded } from "../useDashboard";
import { Section } from "./Section";

export function Positions({ value }: { value: Loaded<PortfolioValue> }) {
  return (
    <Section title="Positions" state={value}>
      {(v) => {
        const rows = positionRows(v.positions, Number(v.total_value));
        if (rows.length === 0) return <p className="muted">No positions yet — the portfolio is all cash.</p>;
        return (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th className="num">Shares</th>
                  <th className="num">Avg cost</th>
                  <th className="num">Price</th>
                  <th className="num">Market value</th>
                  <th className="num">Unrealized P&amp;L</th>
                  <th className="num">Weight</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.symbol}>
                    <td className="symbol">{r.symbol}</td>
                    <td className="num">{quantity(r.quantity)}</td>
                    <td className="num">{money(r.averageCost)}</td>
                    <td className="num">
                      {money(r.price)}
                      {r.pricedAtCost && (
                        <span className="badge" title="No market price available; valued at cost">
                          at cost
                        </span>
                      )}
                    </td>
                    <td className="num">{money(r.marketValue)}</td>
                    <td className={`num ${tone(r.unrealizedPnl)}`}>
                      {signedMoney(r.unrealizedPnl)}
                      <span className="sub">{percent(r.unrealizedPct, { signed: true })}</span>
                    </td>
                    <td className="num">{percent(r.weight, { digits: 1 })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      }}
    </Section>
  );
}
