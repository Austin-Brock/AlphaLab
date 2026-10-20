import { useState } from "react";

import { api } from "../api";

interface Props {
  isOwner: boolean;
  onSignIn: (key: string) => void;
  onSignOut: () => void;
}

/** Visitors see a read-only dashboard; the owner unlocks pause/resume with the admin key. */
export function OwnerSignIn({ isOwner, onSignIn, onSignOut }: Props) {
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  if (isOwner) {
    return (
      <span className="owner">
        <span className="pill pill-up">Owner</span>
        <button className="link small" onClick={onSignOut}>
          Sign out
        </button>
      </span>
    );
  }
  if (!open) {
    return (
      <button className="link small" onClick={() => setOpen(true)}>
        Owner sign-in
      </button>
    );
  }
  return (
    <form
      className="owner-form"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError(undefined);
        try {
          await api.checkAdminKey(key.trim());
          onSignIn(key.trim());
          setOpen(false);
          setKey("");
        } catch {
          setError("Key not accepted");
        } finally {
          setBusy(false);
        }
      }}
    >
      <input
        type="password"
        autoFocus
        autoComplete="current-password"
        placeholder="Admin key"
        aria-label="Admin key"
        value={key}
        onChange={(e) => setKey(e.target.value)}
      />
      <button type="submit" className="primary" disabled={busy || !key.trim()}>
        {busy ? "Checking…" : "Sign in"}
      </button>
      <button type="button" className="ghost" onClick={() => setOpen(false)}>
        Cancel
      </button>
      {error && <span className="down small">{error}</span>}
    </form>
  );
}
