---
name: CSS bundle cascade order
description: Why the optimized Next.js CSS bundle must not depend on module import order for shared theme ownership.
---

Do not rely on stylesheet import order to make shared theme overrides win. Keep shared visual properties in one theme source and remove conflicting declarations from page styles; use explicit cascade layers if overlap is unavoidable.

**Why:** The optimized Next.js bundle reordered stylesheet modules relative to their JSX import order, allowing old page colors to beat a later-looking dark override in source.

**How to apply:** When shared and page CSS target the same component, page CSS should own layout only and consume shared tokens. Validate the optimized production build because development source order is not sufficient evidence.