#!/usr/bin/env bash
# Simple helper to bootstrap and launch the Vite frontend.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"

if ! command -v npm >/dev/null 2>&1; then
  echo "❌ npm n'est pas disponible dans le PATH." >&2
  exit 1
fi

cd "$FRONTEND_DIR"

if [ "${SKIP_INSTALL:-0}" != "1" ]; then
  echo "➡️  Installation des dépendances frontend"
  npm install
fi

ARGS=()
if [ -n "${HOST:-}" ]; then
  ARGS+=("--host" "$HOST")
fi

if [ "${OPEN_BROWSER:-0}" = "1" ]; then
  ARGS+=("--open")
fi

if [ "${HTTPS:-0}" = "1" ]; then
  ARGS+=("--https")
fi

CMD=(npm run dev)
if [ "${#ARGS[@]}" -gt 0 ]; then
  CMD+=(-- "${ARGS[@]}")
fi

echo "➡️  Lancement du frontend Vite"
exec "${CMD[@]}"
