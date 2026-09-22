---
name: Parallel validation isolation
description: Keep concurrent validation commands from mutating artifacts used by other checks or the running app
---

Browser-test builds must run from an isolated working copy rather than deleting or replacing files in the normal frontend tree.

**Why:** Configured validation commands can run concurrently. Isolating only the final export is insufficient because frontend builds can still rewrite shared intermediate caches and generated source or public files. Those races can fail checks, corrupt build IDs, or leave the running app on a test-only build.

**How to apply:** Copy frontend source into a temporary working tree, share dependency directories read-only, and keep all build-generated files inside that tree. Point only the test server at its export, then verify the full parallel workflow repeatedly.