import type { MarketClock, Portfolio } from "../api";
import { when } from "../format";
import { REFRESH_SECONDS } from "../useDashboard";

interface Props {
  portfolios: Portfolio[];
  selected: Portfolio;
  onSelect: (id: string) => void;
  clock?: MarketClock;
  updatedAt?: Date;
  loading: boolean;
  onRefresh: () => void;
}

export function Header({ portfolios, selected, onSelect, clock, updatedAt, loading, onRefresh }: Props) {
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <div className="brand">
          <span className="logo" aria-hidden>
            <svg viewBox="0 0 32 32" width="28" height="28">
              <rect width="32" height="32" rx="7" fill="var(--accent)" />
              <path d="M7 22l6-7 5 4 7-9" stroke="white" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          <span className="brand-name">AlphaLab</span>
          <span className="tag">Simulated money</span>
        </div>

        <label className="picker">
          <span className="visually-hidden">Portfolio</span>
          <select value={selected.id} onChange={(e) => onSelect(e.target.value)}>
            {portfolios.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>

        <div className="topbar-status">
          {clock && (
            <span
              className={`pill ${clock.is_open ? "pill-up" : "pill-muted"}`}
              title={clock.is_open ? `Closes ${when(clock.next_close)}` : `Opens ${when(clock.next_open)}`}
            >
              <span className="dot" /> Market {clock.is_open ? "open" : "closed"}
            </span>
          )}
          <button className="ghost" onClick={onRefresh} disabled={loading} title={`Refreshes every ${REFRESH_SECONDS}s`}>
            {loading ? "Refreshing…" : updatedAt ? `Updated ${updatedAt.toLocaleTimeString()}` : "Refresh"}
          </button>
        </div>
      </div>
    </header>
  );
}
