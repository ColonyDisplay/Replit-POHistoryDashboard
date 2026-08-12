---
name: Clerk auth on FastAPI (Replit-managed)
description: Quirks of Replit-managed Clerk with a Python/FastAPI backend and Vite SPA
---
- Replit-managed Clerk provisions CLERK_SECRET_KEY / CLERK_PUBLISHABLE_KEY / VITE_CLERK_PUBLISHABLE_KEY only; no CLERK_JWT_KEY. `clerk-backend-api` falls back to JWKS via the secret key — treat JWT_KEY/APP_ORIGIN as optional.
- The Python SDK fails closed when `authorized_parties` is set but the token has no `azp` claim (backend-minted session tokens have none). Only pin azp in production via APP_ORIGIN.
- Session tokens carry no email claim; org-domain restriction is enforced by fetching the user via the Clerk backend API (cached per user_id, fail closed).
- Frontend is now a Next.js static export (`next-ui/out`) served by FastAPI; Replit only auto-populates the VITE_-prefixed Clerk vars (VITE_CLERK_PUBLISHABLE_KEY, prod-only VITE_CLERK_PROXY_URL), so next.config.mjs must map them to NEXT_PUBLIC_ at build time, and the Clerk root must render client-only (dynamic ssr:false) because publishableKeyFromHost reads window.location.
- `@clerk/react` (v2+) has no SignedIn/SignedOut exports — use `<Show when="signed-in">`. Sign-in rendered inline with `routing="hash"` (no router in the SPA).
- FastAPI has no Express Clerk proxy middleware; a prod-only `/api/__clerk/{path}` httpx passthrough replicates it (Clerk-Proxy-Url + Clerk-Secret-Key headers), gated on REPLIT_DEPLOYMENT.
- The FastAPI Clerk proxy must NOT forward the browser's Accept-Encoding: the env has no brotli, so httpx can't decode `br` bodies — proxied responses corrupt silently while still logging 200 (blank page in prod). Drop accept-encoding and let httpx negotiate.
- The proxy must preserve duplicate Set-Cookie headers: building a dict from httpx `headers.items()` collapses them, the browser never gets its Clerk client cookie, and every OAuth callback fails with generic `authorization_invalid` ("You are not authorized to perform this request") no matter how Azure/Clerk are configured. Use `multi_items()` + `resp.headers.append()`.
- Custom Microsoft (Entra) creds in prod Clerk also require: Azure app set to multi-tenant (Clerk uses the /common endpoint → AADSTS50194 otherwise) and optional claims `email` + `xms_edov` on ID and Access tokens.
- Never leave the UI gated only behind `<Show>`: it renders nothing until Clerk loads. Keep a loading spinner + timeout error gate (ClerkGate in main.jsx) so a Clerk stall is visible, not blank.
**Why:** dashboard access for enterprise SSO (EASIE) was unavailable; the email-domain gate is the enforcement backstop.
**How to apply:** any change to auth in po_api.py / next-ui/src/components/ClerkRoot.jsx should preserve these constraints.
