---
name: Nested frontend package installation
description: Package installer directory behavior in the Python-root project
---

The managed Node package installer may initialize a package at the workspace root rather than target the nested frontend package.

**Why:** During dependency recovery it created a separate root manifest instead of updating the existing frontend manifest.

**How to apply:** Check the install destination before trusting success. The managed helper cannot pass npm prefix flags for this layout; preserve the nested package and explicitly target it when reconciling the lockfile. Remove only accidental root artifacts and keep the package firewall enabled.