import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const anonKey = (import.meta.env.VITE_SUPABASE_ANON_KEY ||
  import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY) as string | undefined;

export const supabaseConfigured = Boolean(url?.trim() && anonKey?.trim());

let client: SupabaseClient | null = null;

export function getSupabase(): SupabaseClient | null {
  if (!supabaseConfigured) return null;
  if (!client) {
    client = createClient(url!.trim(), anonKey!.trim(), {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
        flowType: "pkce",
      },
    });
  }
  return client;
}

/** Safe internal redirect paths only — prevents open redirects. */
export function safeRedirectPath(raw: string | null | undefined, fallback = "/"): string {
  if (!raw) return fallback;
  const path = raw.trim();
  if (!path.startsWith("/") || path.startsWith("//") || path.includes("://")) {
    return fallback;
  }
  return path;
}

export function authCallbackUrl(): string {
  return `${window.location.origin}/auth/callback`;
}

export function passwordResetRedirectUrl(): string {
  return `${window.location.origin}/auth/reset-password`;
}
