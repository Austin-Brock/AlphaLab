import type { ReactNode } from "react";

import type { Loaded } from "../useDashboard";

interface Props<T> {
  title: string;
  aside?: ReactNode;
  state: Loaded<T>;
  children: (data: T) => ReactNode;
}

export function Section<T>({ title, aside, state, children }: Props<T>) {
  return (
    <section className="card">
      <header className="card-header">
        <h2>{title}</h2>
        {aside}
      </header>
      {state.error ? (
        <p className="notice error">{state.error}</p>
      ) : state.data === undefined ? (
        <p className="muted">Loading…</p>
      ) : (
        children(state.data)
      )}
    </section>
  );
}
