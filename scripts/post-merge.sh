#!/bin/bash
set -e

# Python deps
pip install -r requirements.txt -q

# Frontend deps + build (only if react-ui exists)
if [ -f react-ui/package.json ]; then
  npm ci --prefix react-ui --no-audit --no-fund
  npm run build --prefix react-ui
fi
