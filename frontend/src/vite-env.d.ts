/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** API base including `/api` suffix. Empty → same-origin `/api`. */
  readonly VITE_API_BASE_URL?: string;
  /** Optional shared gate for production API (`X-API-Secret`). */
  readonly VITE_API_SECRET?: string;
  readonly VITE_SUPABASE_URL?: string;
  readonly VITE_SUPABASE_ANON_KEY?: string;
  readonly VITE_SUPABASE_PUBLISHABLE_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
