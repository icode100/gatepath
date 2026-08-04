"use client";

import {
  createUserWithEmailAndPassword,
  GoogleAuthProvider,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut as firebaseSignOut,
  type User as FirebaseUser,
} from "firebase/auth";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { trackEvent } from "@/lib/firebase/analytics";
import {
  firebaseAuthConfigured,
  getFirebaseAuth,
  getPreparedFirebaseAuth,
} from "@/lib/firebase/client";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api/v1";

export type AuthUser = {
  uid?: string;
  displayName: string | null;
  email: string | null;
  photoURL: string | null;
};

type AuthStatus = "loading" | "guest" | "authenticated" | "unavailable";

type AuthContextValue = {
  user: AuthUser | null;
  status: AuthStatus;
  isConfigured: boolean;
  signInWithGoogle: () => Promise<void>;
  signInWithEmail: (email: string, password: string) => Promise<void>;
  createAccount: (email: string, password: string) => Promise<void>;
  resetPassword: (email: string) => Promise<void>;
  resetProgress: () => Promise<void>;
  signOut: () => Promise<void>;
};

type AuthMeResponse = {
  authenticated?: boolean;
  user?: {
    uid?: unknown;
    display_name?: unknown;
    displayName?: unknown;
    email?: unknown;
    photo_url?: unknown;
    photoURL?: unknown;
  } | null;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function profileFromServer(
  payload: AuthMeResponse,
  firebaseUser: FirebaseUser | null,
): AuthUser {
  const profile = payload.user;
  const stringValue = (value: unknown) =>
    typeof value === "string" && value.trim() ? value : null;

  return {
    uid: stringValue(profile?.uid) ?? firebaseUser?.uid,
    displayName:
      stringValue(profile?.display_name) ??
      stringValue(profile?.displayName) ??
      firebaseUser?.displayName ??
      null,
    email: stringValue(profile?.email) ?? firebaseUser?.email ?? null,
    photoURL:
      stringValue(profile?.photo_url) ??
      stringValue(profile?.photoURL) ??
      firebaseUser?.photoURL ??
      null,
  };
}

async function responseError(response: Response, fallback: string) {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === "string" && payload.detail.trim()) {
      return new Error(payload.detail);
    }
  } catch {
    // Use the stable user-facing fallback for non-JSON responses.
  }
  return new Error(fallback);
}

async function requestCsrfToken(): Promise<string> {
  const response = await fetch(`${API_BASE}/auth/csrf`, {
    credentials: "include",
    cache: "no-store",
  });
  if (!response.ok) {
    throw await responseError(response, "Secure sign-in could not be started.");
  }
  const payload = (await response.json()) as { csrf_token?: unknown };
  if (typeof payload.csrf_token !== "string" || !payload.csrf_token) {
    throw new Error("Secure sign-in could not be started.");
  }
  return payload.csrf_token;
}

export function friendlyAuthError(error: unknown): string {
  const code =
    typeof error === "object" && error !== null && "code" in error
      ? String((error as { code?: unknown }).code)
      : "";

  const messages: Record<string, string> = {
    "auth/account-exists-with-different-credential":
      "An account already exists for this email with another sign-in method.",
    "auth/email-already-in-use": "An account already exists for this email.",
    "auth/invalid-credential": "The email or password is incorrect.",
    "auth/invalid-email": "Enter a valid email address.",
    "auth/popup-blocked": "Your browser blocked the Google sign-in window.",
    "auth/popup-closed-by-user": "Google sign-in was cancelled.",
    "auth/too-many-requests": "Too many attempts. Please wait and try again.",
    "auth/weak-password": "Use a password with at least 6 characters.",
  };

  if (messages[code]) return messages[code];
  if (error instanceof Error && error.message) return error.message;
  return "Authentication is temporarily unavailable. You can keep studying as a guest.";
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");

  useEffect(() => {
    let active = true;

    const loadServerSession = async () => {
      try {
        const response = await fetch(`${API_BASE}/auth/me`, {
          credentials: "include",
          cache: "no-store",
        });
        if (!response.ok) throw new Error("Session unavailable");
        const payload = (await response.json()) as AuthMeResponse;
        if (!active) return;
        if (payload.authenticated) {
          setUser(profileFromServer(payload, null));
          setStatus("authenticated");
        } else {
          setUser(null);
          setStatus("guest");
        }
      } catch {
        if (!active) return;
        setUser(null);
        setStatus("unavailable");
      }
    };

    // The HttpOnly backend cookie is authoritative. Browser Firebase setup is
    // prepared independently and is only needed when starting a new sign-in.
    void loadServerSession();
    void getPreparedFirebaseAuth().catch(() => null);

    return () => {
      active = false;
    };
  }, []);

  const exchangeSession = useCallback(
    async (firebaseUser: FirebaseUser, eventName: "login" | "sign_up", method: string) => {
      const csrfToken = await requestCsrfToken();
      const idToken = await firebaseUser.getIdToken(true);
      const response = await fetch(`${API_BASE}/auth/session`, {
        method: "POST",
        credentials: "include",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id_token: idToken, csrf_token: csrfToken }),
      });
      if (!response.ok) {
        throw await responseError(
          response,
          "Your account was verified, but progress sync could not be enabled.",
        );
      }
      await trackEvent(eventName, { method });
      window.location.reload();
    },
    [],
  );

  const signInWithGoogle = useCallback(async () => {
    const auth = await getPreparedFirebaseAuth();
    if (!auth) throw new Error("Firebase sign-in is not configured yet.");
    const provider = new GoogleAuthProvider();
    provider.setCustomParameters({ prompt: "select_account" });
    const result = await signInWithPopup(auth, provider);
    try {
      await exchangeSession(result.user, "login", "google");
    } catch (error) {
      await firebaseSignOut(auth).catch(() => undefined);
      throw error;
    }
  }, [exchangeSession]);

  const signInWithEmail = useCallback(
    async (email: string, password: string) => {
      const auth = await getPreparedFirebaseAuth();
      if (!auth) throw new Error("Firebase sign-in is not configured yet.");
      const result = await signInWithEmailAndPassword(auth, email, password);
      try {
        await exchangeSession(result.user, "login", "password");
      } catch (error) {
        await firebaseSignOut(auth).catch(() => undefined);
        throw error;
      }
    },
    [exchangeSession],
  );

  const createAccount = useCallback(
    async (email: string, password: string) => {
      const auth = await getPreparedFirebaseAuth();
      if (!auth) throw new Error("Firebase sign-in is not configured yet.");
      const result = await createUserWithEmailAndPassword(auth, email, password);
      try {
        await exchangeSession(result.user, "sign_up", "password");
      } catch (error) {
        await firebaseSignOut(auth).catch(() => undefined);
        throw error;
      }
    },
    [exchangeSession],
  );

  const resetPassword = useCallback(async (email: string) => {
    const auth = await getPreparedFirebaseAuth();
    if (!auth) throw new Error("Firebase sign-in is not configured yet.");
    await sendPasswordResetEmail(auth, email);
    await trackEvent("password_reset_requested", { method: "email" });
  }, []);

  const resetProgress = useCallback(async () => {
    const csrfToken = await requestCsrfToken();
    const response = await fetch(`${API_BASE}/progress/reset`, {
      method: "POST",
      credentials: "include",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        csrf_token: csrfToken,
        confirmation: "RESET",
      }),
    });
    if (!response.ok) {
      throw await responseError(
        response,
        "Your progress could not be reset. Please try again.",
      );
    }
    await trackEvent("progress_reset", { method: "account_settings" });
  }, []);

  const signOut = useCallback(async () => {
    const csrfToken = await requestCsrfToken();
    const response = await fetch(`${API_BASE}/auth/logout`, {
      method: "POST",
      credentials: "include",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ csrf_token: csrfToken }),
    });
    if (!response.ok) {
      throw await responseError(response, "Sign-out could not be completed.");
    }

    const auth = getFirebaseAuth();
    if (auth) await firebaseSignOut(auth).catch(() => undefined);
    await trackEvent("logout", { method: "account_menu" });
    window.location.reload();
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      status,
      isConfigured: firebaseAuthConfigured,
      signInWithGoogle,
      signInWithEmail,
      createAccount,
      resetPassword,
      resetProgress,
      signOut,
    }),
    [
      createAccount,
      resetPassword,
      resetProgress,
      signInWithEmail,
      signInWithGoogle,
      signOut,
      status,
      user,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
