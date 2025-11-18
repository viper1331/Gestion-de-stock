#!/usr/bin/env bash
# Simple helper to bootstrap and launch the Vite frontend.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"

HOST="0.0.0.0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      HOST="$2"
      shift 2
      ;;
    *)
      echo "Option inconnue : $1" >&2
      exit 1
      ;;
  esac
done

if ! command -v npm >/dev/null 2>&1; then
  echo "❌ npm n'est pas disponible dans le PATH." >&2
  exit 1
fi

cd "$FRONTEND_DIR"

if [ "${SKIP_INSTALL:-0}" != "1" ]; then
  echo "➡️  Installation des dépendances frontend"
  npm install
fi

ARGS=("--host" "$HOST")

if [ "${OPEN_BROWSER:-0}" = "1" ]; then
  ARGS+=("--open")
fi

if [ "${HTTPS:-0}" = "1" ]; then
  ARGS+=("--https")
fi

echo "➡️  Lancement du frontend Vite sur $HOST"
exec npm run dev -- "${ARGS[@]}"
