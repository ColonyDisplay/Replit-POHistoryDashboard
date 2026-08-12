#!/bin/bash
set -e

# Python deps
pip install -r requirements.txt -q

# Frontend deps + build (only if next-ui exists)
if [ -f next-ui/package.json ]; then
  npm ci --prefix next-ui --no-audit --no-fund
  npm run build --prefix next-ui
fi
