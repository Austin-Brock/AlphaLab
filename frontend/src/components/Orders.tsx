import { Fragment, useState } from "react";

import type { Order } from "../api";
import { money, quantity, when } from "../format";
import type { Loaded } from "../useDashboard";
import { Section } from "./Section";

export function Orders({ orders }: { orders: Loaded<Order[]> }) {
  const [open, setOpen] = useState<string>();
  return (
    <Section
      title="Trade history"
      aside={orders.data && <span className="muted">{orders.data.length} orders · click a row for risk checks</span>}
      state={orders}
    >
      {(list) =>
        list.length === 0 ? (
          <p className="muted">No orders yet.</p>
        ) : (
          <div className="table-wrap">
            <table className="clickable">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th className="num">Shares</th>
                  <th>Status</th>
                  <th className="num">Fill price</th>
                  <th className="num">Value</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {list.map((o) => (
                  <Fragment key={o.id}>
                    <tr onClick={() => setOpen(open === o.id ? undefined : o.id)} aria-expanded={open === o.id}>
                      <td className="nowrap">{when(o.created_at)}</td>
                      <td className="symbol">{o.symbol}</td>
                      <td><SidePill side={o.side} /></td>
                      <td className="num">{quantity(o.quantity)}</td>
                      <td><OrderStatusPill order={o} /></td>
                      <td className="num">{o.execution ? money(o.execution.price) : "—"}</td>
                      <td className="num">{o.execution ? money(o.execution.gross_amount) : "—"}</td>
                      <td className="muted">{o.source}</td>
                    </tr>
                    {open === o.id && (
                      <tr className="detail-row">
                        <td colSpan={8}>
                          <OrderDetail order={o} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )
      }
    </Section>
  );
}

export function OrderDetail({ order }: { order: Order }) {
  return (
    <div className="order-detail">
      {order.rejection_reason && <p className="down">Rejected: {order.rejection_reason}</p>}
      {order.execution && (
        <p className="muted">
          Market price {money(order.execution.market_price)} → filled at {money(order.execution.price)} (0.05% slippage),
          commission {money(order.execution.commission)}, {when(order.execution.executed_at)}
        </p>
      )}
      <ul className="checks">
        {order.risk_checks.map((c) => (
          <li key={c.check_name} className={c.passed ? "up" : "down"}>
            <span aria-hidden>{c.passed ? "✓" : "✗"}</span> <strong>{c.check_name.replace(/_/g, " ")}</strong>{" "}
            <span className="muted">{c.message}</span>
          </li>
        ))}
      </ul>
      <p className="muted mono">client_order_id: {order.client_order_id}</p>
    </div>
  );
}

export function SidePill({ side }: { side: Order["side"] }) {
  return <span className={`pill ${side === "BUY" ? "pill-up" : "pill-down"}`}>{side}</span>;
}

export function OrderStatusPill({ order }: { order: Order }) {
  const cls = { FILLED: "pill-up", REJECTED: "pill-down", PENDING: "pill-muted" }[order.status];
  return (
    <span className={`pill ${cls}`} title={order.rejection_reason ?? undefined}>
      {order.status}
    </span>
  );
}
