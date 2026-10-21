import { useState } from "react";

import { api, ApiError, type Portfolio } from "../api";

interface Props {
  portfolio: Portfolio;
  isOwner: boolean;
  onChanged: () => void;
  onUnauthorized: () => void;
}

/** Whether the scheduled daily AI run trades this portfolio. Only AI portfolios can opt in. */
export function AutoTradeControl({ portfolio, isOwner, onChanged, onUnauthorized }: Props) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  if (!portfolio.strategy_id.startsWith("ai-") || portfolio.status === "CLOSED") return null;

  const on = portfolio.auto_trade;
  const toggle = async () => {
    setBusy(true);
    setError(undefined);
    try {
      await api.setAutoTrade(portfolio.id, !on);
      setConfirming(false);
      onChanged();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) onUnauthorized();
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="control control-slim">
      <div className="control-text">
        <strong>Auto-trade is {on ? "on" : "off"}</strong>
        <span className="muted">
          {on
            ? "The AI runs once each trading day around 10am ET."
            : "The AI only runs when the owner starts it."}
        </span>
      </div>
      {isOwner &&
        (confirming ? (
          <div className="control-confirm">
            <button className={on ? "ghost" : "primary"} onClick={() => void toggle()} disabled={busy}>
              {busy ? "Saving…" : on ? "Yes, turn off" : "Yes, trade daily"}
            </button>
            <button className="ghost" onClick={() => setConfirming(false)} disabled={busy}>
              Cancel
            </button>
          </div>
        ) : (
          <button className={on ? "ghost" : "primary"} onClick={() => setConfirming(true)}>
            {on ? "Turn off auto-trade" : "Turn on auto-trade"}
          </button>
        ))}
      {error && <p className="down small control-error">{error}</p>}
    </div>
  );
}
