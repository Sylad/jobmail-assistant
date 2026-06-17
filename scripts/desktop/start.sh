#!/usr/bin/env bash
# Démarre ollama (smart) + uvicorn pour l'app de bureau JobMail.
set -uo pipefail

REPO_DIR="${JOBMAIL_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
STATE_DIR="${JOBMAIL_STATE_DIR:-$HOME/.jobmail}"
OLLAMA_BIN="${OLLAMA_BIN:-$HOME/.local/ollama/bin/ollama}"
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
SERVE_CMD="${JOBMAIL_SERVE_CMD:-$REPO_DIR/.venv/bin/python -m jobmail serve}"

mkdir -p "$STATE_DIR"

# 1. Idempotence : tuer un uvicorn JobMail resté d'une session précédente.
if [[ -f "$STATE_DIR/jobmail.pid" ]]; then
  old="$(cat "$STATE_DIR/jobmail.pid")"
  [[ -n "$old" ]] && kill -0 "$old" 2>/dev/null && kill "$old" 2>/dev/null || true
  rm -f "$STATE_DIR/jobmail.pid"
fi

# 2. Ollama smart : démarrer seulement s'il ne répond pas déjà.
if curl -sf "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
  echo "ollama déjà actif — on n'y touche pas"
else
  echo "démarrage d'ollama..."
  nohup "$OLLAMA_BIN" serve > "$STATE_DIR/ollama.log" 2>&1 &
  echo $! > "$STATE_DIR/ollama.pid"
  touch "$STATE_DIR/ollama.started-by-jobmail"
fi

# 3. Démarrer uvicorn (jobmail serve) en arrière-plan.
echo "démarrage de jobmail serve..."
cd "$REPO_DIR"
nohup $SERVE_CMD > "$STATE_DIR/jobmail.log" 2>&1 &
echo $! > "$STATE_DIR/jobmail.pid"

echo "started"
