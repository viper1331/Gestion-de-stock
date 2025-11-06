#!/usr/bin/env bash
# Simple helper to bootstrap and launch the FastAPI backend.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"

cd "$BACKEND_DIR"

python_bin="${PYTHON_BIN:-python3}"

if [ ! -d ".venv" ]; then
  echo "➡️  Création de l'environnement virtuel (.venv)"
  "$python_bin" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

if [ "${SKIP_INSTALL:-0}" != "1" ]; then
  echo "➡️  Installation des dépendances backend"
  pip install -r requirements.txt
fi

if [ "${SKIP_TESTS:-0}" != "1" ]; then
  echo "➡️  Exécution de la suite de tests"
  pytest
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
EXTRA_ARGS=()
if [ "${RELOAD:-1}" = "1" ]; then
  EXTRA_ARGS+=("--reload")
fi

echo "➡️  Lancement du backend FastAPI sur $HOST:$PORT"
if [ "${#EXTRA_ARGS[@]}" -gt 0 ]; then
  exec uvicorn backend.app:app --host "$HOST" --port "$PORT" "${EXTRA_ARGS[@]}"
else
  exec uvicorn backend.app:app --host "$HOST" --port "$PORT"
fi
