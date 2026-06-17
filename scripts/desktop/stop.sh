#!/usr/bin/env bash
# Stoppe uvicorn, et ollama uniquement si JobMail l'a démarré.
set -uo pipefail

STATE_DIR="${JOBMAIL_STATE_DIR:-$HOME/.jobmail}"

_kill_pidfile() {
  local f="$1" pid
  [[ -f "$f" ]] || return 0
  pid="$(cat "$f")"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    # Fix 2: escalade SIGKILL si le processus survit au SIGTERM (5 × 0.2s).
    local _n
    for _n in 1 2 3 4 5; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.2
    done
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$f"
}

# 1. Toujours stopper uvicorn.
_kill_pidfile "$STATE_DIR/jobmail.pid"

# 2. Stopper ollama seulement si on l'a démarré.
if [[ -f "$STATE_DIR/ollama.started-by-jobmail" ]]; then
  _kill_pidfile "$STATE_DIR/ollama.pid"
  rm -f "$STATE_DIR/ollama.started-by-jobmail"
fi

echo "stopped"
