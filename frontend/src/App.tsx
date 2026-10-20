import { useEffect, useState } from "react";

import { api, type Portfolio } from "./api";
import { AgentRuns } from "./components/AgentRuns";
import { Header } from "./components/Header";
import { Orders } from "./components/Orders";
import { Overview } from "./components/Overview";
import { Positions } from "./components/Positions";
import { useDashboard } from "./useDashboard";

function portfolioFromHash(): string | undefined {
  return window.location.hash.replace(/^#/, "") || undefined;
}

export function App() {
  const [portfolios, setPortfolios] = useState<Portfolio[]>();
  const [loadError, setLoadError] = useState<string>();
  const [selectedId, setSelectedId] = useState(portfolioFromHash);

  useEffect(() => {
    api
      .portfolios()
      .then(setPortfolios)
      .catch((e: Error) => setLoadError(e.message));
    const onHash = () => setSelectedId(portfolioFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const portfolio = portfolios?.find((p) => p.id === selectedId) ?? portfolios?.[0];
  const dashboard = useDashboard(portfolio?.id);

  if (loadError) {
    return (
      <main className="page">
        <div className="notice error">
          <h2>Can't reach the AlphaLab API</h2>
          <p>{loadError}</p>
          <p>
            Start the backend with <code>cd backend && uv run uvicorn app.main:app --reload</code>,
            then reload this page.
          </p>
        </div>
      </main>
    );
  }
  if (!portfolios) return <main className="page muted">Loading…</main>;
  if (!portfolio) {
    return (
      <main className="page">
        <div className="notice">
          No portfolios yet. Create one with <code>cd backend && uv run python -m app.seed</code>.
        </div>
      </main>
    );
  }

  return (
    <>
      <Header
        portfolios={portfolios}
        selected={portfolio}
        onSelect={(id) => (window.location.hash = id)}
        clock={dashboard.clock.data}
        updatedAt={dashboard.updatedAt}
        loading={dashboard.loading}
        onRefresh={() => void dashboard.refresh()}
      />
      <main className="page">
        <Overview portfolio={portfolio} value={dashboard.value} />
        <Positions value={dashboard.value} />
        <AgentRuns portfolioId={portfolio.id} runs={dashboard.runs} />
        <Orders orders={dashboard.orders} />
      </main>
    </>
  );
}
