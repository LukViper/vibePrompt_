/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** API base including `/api` suffix. Empty → same-origin `/api`. */
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_SUPABASE_URL?: string;
  readonly VITE_SUPABASE_ANON_KEY?: string;
  readonly VITE_SUPABASE_PUBLISHABLE_KEY?: string;
  /** Google Identity Services OAuth client ID (must match backend GOOGLE_OAUTH_CLIENT_ID). */
  readonly VITE_GOOGLE_CLIENT_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
