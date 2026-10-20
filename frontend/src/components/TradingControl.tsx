import { useState } from "react";

import { api, type Portfolio, type StatusChange } from "../api";
import { when } from "../format";

interface Props {
  portfolio: Portfolio;
  lastChange?: StatusChange;
  onChanged: () => void;
}

/** The trading brake: pausing makes the risk engine reject every order and skips AI runs. */
export function TradingControl({ portfolio, lastChange, onChanged }: Props) {
  const [confirming, setConfirming] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  if (portfolio.status === "CLOSED") {
    return <div className="control control-closed">This portfolio is closed. It can't trade.</div>;
  }

  const paused = portfolio.status === "PAUSED";
  const act = async () => {
    setBusy(true);
    setError(undefined);
    try {
      await (paused ? api.resume(portfolio.id) : api.pause(portfolio.id, reason.trim()));
      setConfirming(false);
      setReason("");
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`control ${paused ? "control-paused" : ""}`}>
      <div className="control-text">
        <strong>{paused ? "Trading is paused" : "Trading is on"}</strong>
        <span className="muted">
          {paused
            ? `Every order is rejected and AI runs are skipped.${
                lastChange?.to_status === "PAUSED"
                  ? ` Paused ${when(lastChange.created_at)}${lastChange.reason ? `: “${lastChange.reason}”` : "."}`
                  : ""
              }`
            : "Orders and AI runs go through the risk engine as normal."}
        </span>
      </div>

      {!confirming ? (
        <button className={paused ? "primary" : "danger"} onClick={() => setConfirming(true)}>
          {paused ? "Resume trading" : "Pause trading"}
        </button>
      ) : (
        <form
          className="control-confirm"
          onSubmit={(e) => {
            e.preventDefault();
            void act();
          }}
        >
          {!paused && (
            <input
              autoFocus
              placeholder="Reason (optional)"
              value={reason}
              maxLength={500}
              onChange={(e) => setReason(e.target.value)}
            />
          )}
          <button type="submit" className={paused ? "primary" : "danger"} disabled={busy}>
            {busy ? "Saving…" : paused ? "Yes, resume" : "Yes, pause"}
          </button>
          <button type="button" className="ghost" onClick={() => setConfirming(false)} disabled={busy}>
            Cancel
          </button>
        </form>
      )}
      {error && <p className="down small control-error">{error}</p>}
    </div>
  );
}
