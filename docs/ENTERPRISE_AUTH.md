# Enterprise auth (Phase 1)

## Available now

| Mechanism | Status |
|---|---|
| Guest JWT | Onboarding bootstrap (`POST /api/v1/auth/guest`) |
| Email/password + bcrypt | Legacy local auth |
| Google GIS ID token | `POST /api/v1/auth/google` |
| Supabase OAuth (Google/GitHub) | Configure in Supabase dashboard + `SUPABASE_*` env |
| Org RBAC | `admin` / `member` / `viewer` on `org_memberships` |
| TOTP MFA | `POST /api/v1/auth/mfa/setup` + `/enable` (recommended for paid) |

### RBAC gates

- **viewer** — read project; cannot resolve findings or export specs
- **member** / **admin** — resolve findings, export specs
- **admin** — org billing + membership (extend as needed)

## Team SAML / SSO

SAML via **Supabase SSO** (Okta, Azure AD, Google Workspace) or Auth0 enterprise connection:

1. Upgrade org plan to `team` (Stripe).
2. Enable SSO in Supabase Dashboard → Authentication → SSO.
3. Set `organizations.saml_enabled = 1` for the org (ops/admin).
4. Users sign in through the IdP; JWT validation uses existing Supabase JWKS path.

VibePrompt does not embed a SAML ACS endpoint in-process; the IdP terminates at Supabase/Auth0, then the SPA exchanges the session for API calls as today.
