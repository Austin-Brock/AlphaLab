import { useEffect, useState } from "react";

import { api, ApiError, loadAdminKey, setAdminKey, type Portfolio } from "./api";
import { AgentRuns } from "./components/AgentRuns";
import { Header } from "./components/Header";
import { Orders } from "./components/Orders";
import { Overview } from "./components/Overview";
import { Positions } from "./components/Positions";
import { TradingControl } from "./components/TradingControl";
import { useDashboard } from "./useDashboard";

function portfolioFromHash(): string | undefined {
  return window.location.hash.replace(/^#/, "") || undefined;
}

export function App() {
  const [portfolios, setPortfolios] = useState<Portfolio[]>();
  const [loadError, setLoadError] = useState<string>();
  const [selectedId, setSelectedId] = useState(portfolioFromHash);
  const [isOwner, setIsOwner] = useState(false);

  const signIn = (key: string) => {
    setAdminKey(key);
    setIsOwner(true);
  };
  const signOut = () => {
    setAdminKey(undefined);
    setIsOwner(false);
  };

  useEffect(() => {
    // Re-check a remembered key; drop it if the server no longer accepts it.
    const key = loadAdminKey();
    if (!key) return;
    api
      .checkAdminKey(key)
      .then(() => setIsOwner(true))
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) signOut();
      });
  }, []);

  const loadPortfolios = () =>
    api
      .portfolios()
      .then(setPortfolios)
      .catch((e: Error) => setLoadError(e.message));

  useEffect(() => {
    void loadPortfolios();
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
        isOwner={isOwner}
        onSignIn={signIn}
        onSignOut={signOut}
      />
      <main className="page">
        <TradingControl
          portfolio={portfolio}
          lastChange={dashboard.statusChanges.data?.[0]}
          isOwner={isOwner}
          onUnauthorized={signOut}
          onChanged={() => {
            void loadPortfolios();
            void dashboard.refresh();
          }}
        />
        <Overview portfolio={portfolio} value={dashboard.value} />
        <Positions value={dashboard.value} />
        <AgentRuns portfolioId={portfolio.id} runs={dashboard.runs} />
        <Orders orders={dashboard.orders} />
      </main>
    </>
  );
}
