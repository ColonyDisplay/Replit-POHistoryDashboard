---
name: Next static export routes
description: Routing and preview-cache rules for top-level Next pages served by FastAPI.
---

When a Next static export emits a flat `page.html`, Starlette's HTML-mode static mount does not map `/page` to that file. Every top-level page must have an explicit FastAPI route for both `/page` and `/page/`, supporting flat and nested export layouts.

**Why:** Without the explicit route, direct visits and refreshes render the exported 404 even though the page built successfully. In preview mode, omitting the trailing-slash form from no-store handling can also leave stale HTML cached after rebuilds.

**How to apply:** Whenever a top-level Next route is added, register both URL forms before the static mount, resolve either export layout, fail explicitly when the page was not built, and include both URL forms in preview HTML cache rules and route tests.