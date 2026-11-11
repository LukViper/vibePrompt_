import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { Session, User } from "@supabase/supabase-js";
import { api, setToken } from "../api/client";
import { authCallbackUrl, getSupabase, passwordResetRedirectUrl, supabaseConfigured } from "../lib/supabase";
import type { AuthConfigPublic, UserPublic } from "../types";

type AuthContextValue = {
  loading: boolean;
  config: AuthConfigPublic | null;
  session: Session | null;
  supabaseUser: User | null;
  profile: UserPublic | null;
  error: string | null;
  clearError: () => void;
  usingSupabase: boolean;
  signInWithPassword: (email: string, password: string) => Promise<void>;
  signUpWithPassword: (email: string, password: string) => Promise<{ needsEmailConfirm: boolean }>;
  signInWithOAuth: (provider: "google" | "github") => Promise<void>;
  signInLegacy: (email: string, password: string) => Promise<void>;
  registerLegacy: (email: string, password: string) => Promise<void>;
  resetPasswordForEmail: (email: string) => Promise<void>;
  updatePassword: (password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshProfile: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function providerFromUser(user: User | null): string {
  const fromApp = user?.app_metadata?.provider;
  if (typeof fromApp === "string" && fromApp) return fromApp;
  const identities = user?.identities;
  if (identities && identities.length > 0 && identities[0]?.provider) {
    return identities[0].provider;
  }
  return "email";
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [config, setConfig] = useState<AuthConfigPublic | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [supabaseUser, setSupabaseUser] = useState<User | null>(null);
  const [profile, setProfile] = useState<UserPublic | null>(null);
  const [error, setError] = useState<string | null>(null);

  const usingSupabase = Boolean(
    config?.mode === "supabase" || (supabaseConfigured && config?.supabase_configured)
  );

  const syncBackendProfile = useCallback(async (sess: Session | null, user: User | null) => {
    if (!sess?.access_token) {
      setToken(null);
      setProfile(null);
      return;
    }
    setToken(sess.access_token);
    const meta = user?.user_metadata ?? {};
    const display =
      (typeof meta.full_name === "string" && meta.full_name) ||
      (typeof meta.name === "string" && meta.name) ||
      (typeof meta.user_name === "string" && meta.user_name) ||
      null;
    const avatar =
      (typeof meta.avatar_url === "string" && meta.avatar_url) ||
      (typeof meta.picture === "string" && meta.picture) ||
      null;
    try {
      const synced = await api.syncProfile({
        display_name: display,
        avatar_url: avatar,
        auth_provider: providerFromUser(user),
      });
      setProfile(synced);
    } catch {
      try {
        const me = await api.me();
        setProfile(me);
      } catch {
        setProfile(null);
      }
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const boot = async () => {
      try {
        const cfg = await api.authConfig();
        if (!cancelled) setConfig(cfg);
      } catch {
        if (!cancelled) {
          setConfig({
            mode: supabaseConfigured ? "supabase" : "legacy",
            supabase_configured: supabaseConfigured,
            google_oauth_hint: false,
            github_oauth_hint: false,
            email_auth: true,
          });
        }
      }

      const sb = getSupabase();
      if (sb) {
        const { data } = await sb.auth.getSession();
        if (!cancelled) {
          setSession(data.session);
          setSupabaseUser(data.session?.user ?? null);
          await syncBackendProfile(data.session, data.session?.user ?? null);
        }
        const { data: sub } = sb.auth.onAuthStateChange(async (_event, next) => {
          setSession(next);
          setSupabaseUser(next?.user ?? null);
          await syncBackendProfile(next, next?.user ?? null);
        });
        if (!cancelled) setLoading(false);
        return () => {
          cancelled = true;
          sub.subscription.unsubscribe();
        };
      }

      // Legacy token boot
      try {
        const me = await api.me();
        if (!cancelled) setProfile(me);
      } catch {
        setToken(null);
        if (!cancelled) setProfile(null);
      }
      if (!cancelled) setLoading(false);
      return () => {
        cancelled = true;
      };
    };

    let cleanup: (() => void) | undefined;
    void boot().then((fn) => {
      cleanup = fn;
    });
    return () => {
      cancelled = true;
      cleanup?.();
    };
  }, [syncBackendProfile]);

  const clearError = useCallback(() => setError(null), []);

  const value = useMemo<AuthContextValue>(
    () => ({
      loading,
      config,
      session,
      supabaseUser,
      profile,
      error,
      clearError,
      usingSupabase: Boolean(usingSupabase && getSupabase()),
      signInWithPassword: async (email, password) => {
        setError(null);
        const sb = getSupabase();
        if (!sb) throw new Error("Supabase is not configured");
        const { error: err } = await sb.auth.signInWithPassword({ email, password });
        if (err) {
          setError(err.message);
          throw err;
        }
      },
      signUpWithPassword: async (email, password) => {
        setError(null);
        const sb = getSupabase();
        if (!sb) throw new Error("Supabase is not configured");
        const { data, error: err } = await sb.auth.signUp({
          email,
          password,
          options: { emailRedirectTo: authCallbackUrl() },
        });
        if (err) {
          setError(err.message);
          throw err;
        }
        return { needsEmailConfirm: !data.session };
      },
      signInWithOAuth: async (provider) => {
        setError(null);
        const sb = getSupabase();
        if (!sb) throw new Error("Supabase is not configured");
        const { error: err } = await sb.auth.signInWithOAuth({
          provider,
          options: {
            redirectTo: authCallbackUrl(),
            skipBrowserRedirect: false,
          },
        });
        if (err) {
          setError(err.message);
          throw err;
        }
      },
      signInLegacy: async (email, password) => {
        setError(null);
        const res = await api.login(email, password);
        setToken(res.access_token);
        setProfile(res.user);
      },
      registerLegacy: async (email, password) => {
        setError(null);
        const res = await api.register(email, password);
        setToken(res.access_token);
        setProfile(res.user);
      },
      resetPasswordForEmail: async (email) => {
        setError(null);
        const sb = getSupabase();
        if (!sb) throw new Error("Supabase is not configured");
        const { error: err } = await sb.auth.resetPasswordForEmail(email, {
          redirectTo: passwordResetRedirectUrl(),
        });
        if (err) {
          setError(err.message);
          throw err;
        }
      },
      updatePassword: async (password) => {
        setError(null);
        const sb = getSupabase();
        if (!sb) throw new Error("Supabase is not configured");
        const { error: err } = await sb.auth.updateUser({ password });
        if (err) {
          setError(err.message);
          throw err;
        }
      },
      logout: async () => {
        setError(null);
        const sb = getSupabase();
        if (sb) await sb.auth.signOut();
        setToken(null);
        setSession(null);
        setSupabaseUser(null);
        setProfile(null);
      },
      refreshProfile: async () => {
        const me = await api.me();
        setProfile(me);
      },
    }),
    [
      loading,
      config,
      session,
      supabaseUser,
      profile,
      error,
      clearError,
      usingSupabase,
    ]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
