---
name: DataLake contract boundary
description: Why lake reporting must not inherit the existing Operations KPI upstream assumptions
---

Treat DataLake and the published Operations KPI read model as separate contracts.
Do not infer lake endpoint suffixes, payload schemas or as-of semantics from
the KPI handoff, local reporting endpoint names, or similar services.

**Why:** The lake reporting request explicitly requires confirmed upstream
contracts and permits unavailable responses until services can be configured.
The existing KPI handoff documents Neon views, not the lake services. Guessing
from it would silently invent a service contract and risk exposing the wrong data.

**How to apply:** When enabling a lake report, obtain approved service evidence
before selecting its path, date parameter and safe response fields. Keep the
unavailable state until that evidence exists; distinguish mocked transport
tests from live contract verification.

Keep lake URL configuration environment-only, even though the URLs are public.

**Why:** The project owner explicitly rejected source-code URL defaults in favor
of managing all lake configuration in Replit Tools → Secrets. Public availability
does not imply permission to provide a fallback.

**How to apply:** Retain host/path allowlist rules as validation, not defaults.
Do not reintroduce URL fallbacks when simplifying configuration.

Use the lake token for both approved lake services; never introduce a gateway credential.

**Why:** The service owner subsequently confirmed dual acceptance on lake-health.
The earlier gateway-only restriction and its 401 probe results are obsolete.

**How to apply:** Keep credentials scoped to the approved service destinations
and use LAKE_API_AUTH_TOKEN for either service, without gateway-token fallbacks.