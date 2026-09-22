---
name: Unsigned preview data boundary
description: Source-selection rule for the development-only admin preview
---

Preview mode is an unsigned fallback, not a host-wide replacement for authenticated development access. Valid Clerk sessions keep the normal repository-backed path.

**Why:** The project owner explicitly requested live read-only Preview Admin data
after being informed that this exposes data to anyone who can access the development
preview URL. They rely on workspace access restrictions. Production authentication
must remain unchanged; never describe the preview identity as a verified Clerk admin.

**How to apply:** Live unsigned preview requires explicit development-only opt-in
plus the existing preview host and deployment guards. Preserve blocked writes and
reject invalid presented tokens. Without live opt-in, use fixtures; never silently
substitute fixtures for a failed live request. Never enable this bypass in production.