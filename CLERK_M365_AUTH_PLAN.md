# Clerk + Microsoft 365 Authentication Plan — PO History Detail

Shared authentication plan for both hosting options:

- `VERCEL_MIGRATION_PLAN.md`
- `REPLIT_NEON_MIGRATION_PLAN.md`

Goal: only Colony employees signing in with their Microsoft 365 (Entra ID)
work accounts can reach the dashboard or API. Clerk sits in front as the
auth layer and user-management surface; Microsoft remains the identity
source. No passwords are stored or managed in this project.

## Why Clerk In Front Of M365

- Estimators sign in with the M365 account they already have — no new
  credentials, MFA policy inherited from Entra.
- Clerk gives a hosted sign-in UI, session management, and a user dashboard
  (see who has access, ban/remove users) without writing auth code.
- The same Clerk application works for both hosting targets, so the auth
  work is done once and survives a later Vercel-vs-Replit change of heart.

## Connection Type: EASIE vs SAML

Clerk supports Microsoft Entra ID two ways. Both enroll users by email
domain (`colonydisplay.com`) with just-in-time provisioning.

| | EASIE (OIDC) — recommended | SAML |
|---|---|---|
| Setup | Minimal — no metadata/certificate exchange with IT | IT must configure an Entra enterprise app, exchange Reply URL + Entity ID |
| Tenancy | Multi-tenant Microsoft endpoint; Clerk validates the `xms_edov` claim to prevent tenant crossover | Single-tenant — strictest isolation |
| Dev instances | Works with Clerk's shared dev credentials, zero config | Full setup required even for dev |
| Deprovisioning | Automatic; session revocation within ~10 minutes of removal in Entra | On next SAML assertion expiry |

**Recommendation:** EASIE Microsoft connection. It is purpose-built for
"sign in with Microsoft as org-wide SSO," needs no per-tenant certificate
exchange, and Clerk mitigates the multi-tenant crossover risk by requiring
the `xms_edov` (email-domain-owner-verified) claim. Fall back to SAML only
if IT policy demands a single-tenant integration.

**Entra prerequisite either way:** `colonydisplay.com` must be a verified
domain in the company's Entra tenant (it already is if company mail flows
through M365). For a production Clerk instance, EASIE needs custom
credentials — a one-time Entra app registration whose client ID/secret go
into the Clerk connection config.

## Clerk Application Configuration

1. Create the Clerk application (one app, dev + production instances).
2. **SSO connections → Add connection → For specific domains or
   organizations → Microsoft (EASIE)**, domain `colonydisplay.com`.
3. Sign-in options: disable password, email code, and social sign-ups —
   enterprise SSO only. With domain-based enrollment, anyone at
   `colonydisplay.com` signs in via Microsoft and is provisioned on first
   sign-in; everyone else is rejected.
4. Optional tightening: set sign-up mode to **Restricted** and manage an
   explicit allowlist in the Clerk dashboard if access should be narrower
   than "the whole company."
5. User management happens in the Clerk dashboard: view sessions, ban or
   delete users, audit sign-ins. Removing the user in Entra also kills
   access (EASIE auto-deprovisioning).

## Frontend Changes (React SPA — Same For Both Hosts)

The UI is a Vite React SPA in `react-ui/`, served by FastAPI from
`react-ui/dist` (or by Vercel static hosting under that plan). Clerk's
React SDK is client-only, which fits this setup exactly.

- `npm install @clerk/react` in `react-ui/`.
- `VITE_CLERK_PUBLISHABLE_KEY` in the build environment (Vite inlines it at
  build time — it must be present when `npm run build` runs, not just at
  runtime).
- Wrap the app in `main.tsx`:

```tsx
import { ClerkProvider, SignedIn, SignedOut, RedirectToSignIn } from '@clerk/react'

<ClerkProvider publishableKey={import.meta.env.VITE_CLERK_PUBLISHABLE_KEY}>
  <SignedIn><App /></SignedIn>
  <SignedOut><RedirectToSignIn /></SignedOut>
</ClerkProvider>
```

  With enterprise SSO as the only enabled strategy, the Clerk sign-in page
  shows a single "Continue with Microsoft" path.

- Attach the session token to every API call. The existing fetch helper
  gains one header:

```tsx
const { getToken } = useAuth()
const token = await getToken()
const res = await fetch(`/search?q=${q}`, {
  headers: { Authorization: `Bearer ${token}` },
})
```

- Add a `<UserButton />` (or minimal sign-out control) to the header.

## Backend Verification

### FastAPI (Replit deployment, or Vercel Option A internal API)

Use Clerk's official Python SDK (`clerk-backend-api` on PyPI) with
networkless JWT verification — every request is an in-memory RS256
signature check against the instance's PEM public key, no per-request
call to Clerk.

```python
from clerk_backend_api import AuthenticateRequestOptions
from clerk_backend_api.security import authenticate_request
from fastapi import Depends, HTTPException, Request

def require_auth(request: Request):
    state = authenticate_request(
        request,
        AuthenticateRequestOptions(
            jwt_key=os.environ["CLERK_JWT_KEY"],          # PEM public key → networkless
            authorized_parties=[os.environ["APP_ORIGIN"]], # azp check — do not skip
            accepts_token=["session_token"],
        ),
    )
    if not state.is_signed_in:
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Bearer"})
    return state
```

Apply it once to the whole route set rather than per-endpoint:

```python
app = FastAPI(title="Colony Internal API", dependencies=[Depends(require_auth)])
```

Then exempt what must stay open:

- `/health` — keep unauthenticated for uptime monitors (it leaks only a
  row count; move it to its own unprotected sub-app or check the path in
  the dependency).
- Static files (`react-ui/dist` mount) — must stay public so the SPA and
  the Clerk sign-in flow can load before a session exists. Only API
  routes carry the Bearer requirement.

`/run-script` deserves both the auth dependency **and** the
`ENABLE_SCRIPT_RUNNER` env gate from the Replit plan — auth alone should
not be the only thing between the internet and PowerShell execution.

### Vercel Functions (Vercel Option B only)

If the API is rewritten as Vercel functions, verification is the same
concept with the platform-native SDK: `@clerk/backend`'s
`authenticateRequest()` in Node functions (or the same
`clerk-backend-api` package in Python functions), again with `jwtKey`
for networkless checks and `authorizedParties` pinned to the deployment
origin.

## Environment Variables

| Variable | Where | Notes |
|---|---|---|
| `VITE_CLERK_PUBLISHABLE_KEY` | Build environment (Replit build step / Vercel build) | Public, baked into the JS bundle |
| `CLERK_SECRET_KEY` | Replit Secrets / Vercel env vars | Backend only; needed for Backend API calls and as JWKS fallback |
| `CLERK_JWT_KEY` | Replit Secrets / Vercel env vars | PEM public key from Clerk dashboard → API keys; enables networkless verification |
| `APP_ORIGIN` | Backend | The deployment URL, for `authorized_parties` |

Dev instance keys (`pk_test_`/`sk_test_`) for local work, production keys
(`pk_live_`/`sk_live_`) only in the hosting platform's secret store.
Nothing Clerk-related is committed — consistent with the existing
`secrets/` policy.

## CORS Note

Once the token rides in an `Authorization` header, the browser sends it
only same-origin or to origins the API allows. On Replit (FastAPI serves
the UI) everything is same-origin — the localhost CORS entries can go
away in production. On Vercel Option A (static UI on Vercel, FastAPI
internal), the API's `allow_origins` must include the Vercel deployment
URL and allow the `Authorization` header.

## Rollout Phases

### Phase A — Clerk App + Dev Wiring

Create the Clerk app, enable the EASIE Microsoft connection on the dev
instance (shared credentials, no Entra work yet), disable all other
sign-in strategies. Add `ClerkProvider` to the React app and the
`require_auth` dependency to FastAPI. Verify locally: signed-out users
land on Microsoft sign-in; API returns 401 without a Bearer token.

### Phase B — Production Instance

Entra app registration for EASIE custom credentials (one-time IT task),
production Clerk instance, production keys into the hosting platform's
secret store.

### Phase C — Deploy And Verify

Deploy per the hosting plan. Confirm from an off-LAN device: unauthenticated
requests to API routes return 401, the sign-in flow round-trips through
Microsoft, a colleague outside any allowlist is rejected, and `/health`
still answers for the uptime monitor.

### Phase D — Operational Handover

Document in the Clerk dashboard who administers users. Test the
deprovisioning path once: disable a test account in Entra, confirm the
session dies within the revocation window.

## Effort Summary

| Piece | Size |
|---|---|
| Clerk app + EASIE connection config | Dashboard work, no code |
| React: provider, redirect, token header, user button | ~4 small edits in `react-ui/` |
| FastAPI: one dependency + exemptions | ~30 lines in `po_api.py` |
| Entra app registration (production) | One-time IT task |

The auth layer is deliberately identical across both migration plans:
hosting choice changes where the env vars live and nothing else of
substance.
