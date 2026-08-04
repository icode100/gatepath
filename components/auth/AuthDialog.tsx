"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { friendlyAuthError, useAuth } from "./AuthProvider";

type AuthDialogProps = {
  open: boolean;
  onClose: () => void;
  onProgressReset?: () => void | Promise<void>;
  identityChangeBlocked?: boolean;
};

export function AuthDialog({
  open,
  onClose,
  onProgressReset,
  identityChangeBlocked = false,
}: AuthDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const {
    user,
    status,
    isConfigured,
    signInWithGoogle,
    signInWithEmail,
    createAccount,
    resetPassword,
    resetProgress,
    signOut,
  } = useAuth();
  const [mode, setMode] = useState<"signin" | "create">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [resetConfirming, setResetConfirming] = useState(false);
  const [resetConfirmation, setResetConfirmation] = useState("");

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      setError(null);
      setMessage(null);
      setPassword("");
      setResetConfirming(false);
      setResetConfirmation("");
      dialog.showModal();
    } else if (!open && dialog.open) {
      setPassword("");
      dialog.close();
    }
  }, [open]);

  const run = async (action: () => Promise<void>) => {
    if (identityChangeBlocked) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await action();
    } catch (authError) {
      setError(friendlyAuthError(authError));
      setBusy(false);
    }
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void run(() =>
      mode === "create"
        ? createAccount(email.trim(), password)
        : signInWithEmail(email.trim(), password),
    );
  };

  const handleReset = () => {
    if (!email.trim()) {
      setError("Enter your email address first.");
      return;
    }
    void run(async () => {
      await resetPassword(email.trim());
      setMessage("Password reset instructions have been sent if that account exists.");
      setBusy(false);
    });
  };

  const handleProgressReset = async () => {
    if (identityChangeBlocked || busy) return;
    if (resetConfirmation !== "RESET") {
      setError("Type RESET exactly to confirm.");
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await resetProgress();
      await onProgressReset?.();
      setResetConfirming(false);
      setResetConfirmation("");
      setMessage("Your progress and attempt history have been reset.");
    } catch (resetError) {
      setError(friendlyAuthError(resetError));
    } finally {
      setBusy(false);
    }
  };

  const close = () => {
    if (!busy) {
      setPassword("");
      dialogRef.current?.close();
    }
  };

  const displayName = user?.displayName || user?.email || "Gatepath learner";

  return (
    <dialog
      ref={dialogRef}
      className="auth-dialog"
      aria-labelledby="auth-dialog-title"
      onClose={onClose}
      onCancel={(event) => {
        if (busy) event.preventDefault();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <div className="auth-dialog-card">
        <button
          type="button"
          className="auth-dialog-close"
          aria-label="Close account dialog"
          onClick={close}
          disabled={busy}
        >
          ×
        </button>

        <div className="auth-dialog-heading">
          <span className="auth-dialog-mark">G</span>
          <div>
            <span className="eyebrow">Account &amp; settings</span>
            <h2 id="auth-dialog-title">
              {status === "authenticated" ? "Your study space" : "Sync your progress"}
            </h2>
          </div>
        </div>

        {identityChangeBlocked && (
          <div className="auth-notice" role="status">
            <strong>Finish this session first</strong>
            <span>
              Submit or exit the active practice or test before switching accounts.
              Your current answers stay untouched.
            </span>
          </div>
        )}

        <div className="auth-live-region" aria-live="polite">
          {error && <p className="auth-error">{error}</p>}
          {message && <p className="auth-success">{message}</p>}
        </div>

        {status === "loading" ? (
          <div className="auth-loading" role="status">
            <span /> Checking your study space…
          </div>
        ) : status === "authenticated" && user ? (
          <div className="auth-account">
            <div className="auth-account-profile">
              <span>{displayName.slice(0, 1).toUpperCase()}</span>
              <div>
                <strong>{displayName}</strong>
                {user.email && user.displayName && <small>{user.email}</small>}
              </div>
            </div>
            <p>
              Your attempts and topic analytics are synced through your secure
              Gatepath session.
            </p>
            <button
              type="button"
              className="button quiet full auth-signout"
              disabled={busy || identityChangeBlocked}
              onClick={() => void run(signOut)}
            >
              {busy ? "Signing out…" : "Sign out"}
            </button>
          </div>
        ) : status === "unavailable" ? (
          <div className="auth-unavailable">
            <strong>Your account session could not be checked</strong>
            <p>
              Retry when Firebase is available, or clear this session to
              continue in a new isolated guest profile.
            </p>
            <div className="auth-recovery-actions">
              <button
                type="button"
                className="button quiet full"
                disabled={busy}
                onClick={() => window.location.reload()}
              >
                Retry account check
              </button>
              <button
                type="button"
                className="button primary full"
                disabled={busy || identityChangeBlocked}
                onClick={() => void run(signOut)}
              >
                {busy ? "Switching…" : "Continue as guest"}
              </button>
            </div>
          </div>
        ) : !isConfigured ? (
          <div className="auth-unavailable">
            <strong>Guest mode is ready</strong>
            <p>
              Account sync has not been configured for this deployment. You can
              still use every local study feature.
            </p>
          </div>
        ) : (
          <div className="auth-guest">
            <p className="auth-intro">
              Continue on any device while keeping guest mode available whenever
              you need it.
            </p>
            <button
              type="button"
              className="auth-google"
              disabled={busy || identityChangeBlocked}
              onClick={() => void run(signInWithGoogle)}
            >
              <span>G</span>
              {busy ? "Connecting…" : "Continue with Google"}
            </button>

            <div className="auth-divider"><span>or use email</span></div>

            <form className="auth-form" onSubmit={handleSubmit}>
              <label>
                <span>Email address</span>
                <input
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  autoComplete="email"
                  placeholder="you@example.com"
                  required
                  disabled={busy || identityChangeBlocked}
                />
              </label>
              <label>
                <span>Password</span>
                <input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete={mode === "create" ? "new-password" : "current-password"}
                  minLength={6}
                  placeholder="At least 6 characters"
                  required
                  disabled={busy || identityChangeBlocked}
                />
              </label>

              {mode === "signin" && (
                <button
                  type="button"
                  className="auth-text-button auth-forgot"
                  onClick={handleReset}
                  disabled={busy || identityChangeBlocked}
                >
                  Forgot password?
                </button>
              )}

              <button
                type="submit"
                className="button primary full auth-submit"
                disabled={busy || identityChangeBlocked}
              >
                {busy
                  ? "Please wait…"
                  : mode === "create"
                    ? "Create account"
                    : "Sign in with email"}
              </button>
            </form>

            <p className="auth-switch">
              {mode === "create" ? "Already have an account?" : "New to Gatepath?"}
              <button
                type="button"
                className="auth-text-button"
                disabled={busy || identityChangeBlocked}
                onClick={() => {
                  setMode((current) => current === "signin" ? "create" : "signin");
                  setPassword("");
                  setError(null);
                  setMessage(null);
                }}
              >
                {mode === "create" ? "Sign in" : "Create one"}
              </button>
            </p>
          </div>
        )}

        {status !== "loading" && status !== "unavailable" && (
          <section className="auth-settings" aria-labelledby="study-data-heading">
            <div>
              <span className="eyebrow">Settings · Study data</span>
              <strong id="study-data-heading">Reset progress</strong>
              <p>
                Remove your attempts, test history, and analytics from this
                study profile. The shared question bank and your account stay
                unchanged.
              </p>
            </div>
            {!resetConfirming ? (
              <button
                type="button"
                className="button quiet full auth-reset-trigger"
                disabled={busy || identityChangeBlocked}
                onClick={() => {
                  setResetConfirming(true);
                  setError(null);
                  setMessage(null);
                }}
              >
                Reset progress…
              </button>
            ) : (
              <div className="auth-reset-confirm">
                <label htmlFor="reset-progress-confirmation">
                  Type <strong>RESET</strong> to confirm. This cannot be undone.
                </label>
                <input
                  id="reset-progress-confirmation"
                  value={resetConfirmation}
                  onChange={(event) => setResetConfirmation(event.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                  disabled={busy}
                  placeholder="RESET"
                />
                <div>
                  <button
                    type="button"
                    className="button quiet"
                    disabled={busy}
                    onClick={() => {
                      setResetConfirming(false);
                      setResetConfirmation("");
                      setError(null);
                    }}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="button danger"
                    disabled={
                      busy ||
                      identityChangeBlocked ||
                      resetConfirmation !== "RESET"
                    }
                    onClick={() => void handleProgressReset()}
                  >
                    {busy ? "Resetting…" : "Reset everything"}
                  </button>
                </div>
              </div>
            )}
          </section>
        )}

        <p className="auth-privacy">
          Gatepath never sends your email, answers, or question text to Analytics.
        </p>
      </div>
    </dialog>
  );
}
