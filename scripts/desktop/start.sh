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
_jobmail_started_ollama=0
if curl -sf "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
  echo "ollama déjà actif — on n'y touche pas"
  # Fix 3 (self-healing): supprimer un marqueur/pid stale d'un crash précédent.
  if [[ -f "$STATE_DIR/ollama.started-by-jobmail" ]]; then
    echo "marqueur ollama.started-by-jobmail stale détecté — nettoyage"
    if [[ -f "$STATE_DIR/ollama.pid" ]]; then
      _stale_pid="$(cat "$STATE_DIR/ollama.pid")"
      [[ -n "$_stale_pid" ]] && kill -0 "$_stale_pid" 2>/dev/null && kill "$_stale_pid" 2>/dev/null || true
      rm -f "$STATE_DIR/ollama.pid"
    fi
    rm -f "$STATE_DIR/ollama.started-by-jobmail"
  fi
else
  echo "démarrage d'ollama..."
  nohup "$OLLAMA_BIN" serve > "$STATE_DIR/ollama.log" 2>&1 &
  echo $! > "$STATE_DIR/ollama.pid"
  touch "$STATE_DIR/ollama.started-by-jobmail"
  _jobmail_started_ollama=1
fi

# Fix 1: attendre qu'ollama soit joignable (seulement si on vient de le démarrer).
if [[ "$_jobmail_started_ollama" == "1" ]]; then
  echo "attente ollama prêt (max ${JOBMAIL_OLLAMA_WAIT:-15}s)..."
  for _i in $(seq 1 "${JOBMAIL_OLLAMA_WAIT:-15}"); do
    curl -sf "$OLLAMA_URL/api/tags" >/dev/null 2>&1 && break
    sleep 1
  done
fi

# 3. Démarrer uvicorn (jobmail serve) en arrière-plan.
echo "démarrage de jobmail serve..."
cd "$REPO_DIR"
nohup $SERVE_CMD > "$STATE_DIR/jobmail.log" 2>&1 &
echo $! > "$STATE_DIR/jobmail.pid"

echo "started"
