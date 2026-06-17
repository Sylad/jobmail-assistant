#!/usr/bin/env bash
# Teste la logique ollama-smart de start.sh/stop.sh sans vrais serveurs.
# Mocks: faux `curl` (santé ollama pilotée par FAKE_OLLAMA_UP), faux `ollama` (sleep),
# uvicorn remplacé par `sleep` via JOBMAIL_SERVE_CMD.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
FAILED=0
pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1"; FAILED=1; }

make_env() {
  TMP="$(mktemp -d)"
  BIN="$TMP/bin"; mkdir -p "$BIN"
  STATE="$TMP/state"
  cat > "$BIN/ollama" <<'EOF'
#!/usr/bin/env bash
exec sleep 120
EOF
  cat > "$BIN/curl" <<'EOF'
#!/usr/bin/env bash
# Health check succeeds only when FAKE_OLLAMA_UP=1.
[[ "${FAKE_OLLAMA_UP:-0}" == "1" ]] && exit 0 || exit 7
EOF
  chmod +x "$BIN/ollama" "$BIN/curl"
}

run_start() {
  PATH="$BIN:$PATH" JOBMAIL_STATE_DIR="$STATE" OLLAMA_BIN="$BIN/ollama" \
    OLLAMA_URL="http://localhost:11434" JOBMAIL_REPO="$REPO" \
    JOBMAIL_SERVE_CMD="sleep 120" FAKE_OLLAMA_UP="$1" \
    bash "$REPO/scripts/desktop/start.sh" >/dev/null 2>&1
}
run_stop() {
  PATH="$BIN:$PATH" JOBMAIL_STATE_DIR="$STATE" \
    bash "$REPO/scripts/desktop/stop.sh" >/dev/null 2>&1
}
alive() { local f="$STATE/$1"; [[ -f "$f" ]] && kill -0 "$(cat "$f")" 2>/dev/null; }
cleanup() {
  for f in jobmail.pid ollama.pid; do
    [[ -f "$STATE/$f" ]] && kill "$(cat "$STATE/$f")" 2>/dev/null
  done
  rm -rf "$TMP"
}

# Scenario A: ollama DOWN -> JobMail starts it, sets marker, kills both on stop.
make_env
run_start 0
alive jobmail.pid && pass "A: uvicorn started" || fail "A: uvicorn not started"
alive ollama.pid  && pass "A: ollama started"  || fail "A: ollama not started"
[[ -f "$STATE/ollama.started-by-jobmail" ]] && pass "A: marker set" || fail "A: marker missing"
ollama_pid="$(cat "$STATE/ollama.pid")"; jobmail_pid="$(cat "$STATE/jobmail.pid")"
run_stop
kill -0 "$jobmail_pid" 2>/dev/null && fail "A: uvicorn still alive" || pass "A: uvicorn stopped"
kill -0 "$ollama_pid" 2>/dev/null && fail "A: ollama still alive"  || pass "A: ollama stopped"
[[ -f "$STATE/ollama.started-by-jobmail" ]] && fail "A: marker not cleared" || pass "A: marker cleared"
cleanup

# Scenario B: ollama UP -> JobMail must NOT start it, no marker, stop leaves ollama alone.
make_env
"$BIN/ollama" & external_ollama=$!   # simulate an ollama already running elsewhere
run_start 1
alive jobmail.pid && pass "B: uvicorn started" || fail "B: uvicorn not started"
[[ -f "$STATE/ollama.pid" ]] && fail "B: ollama.pid should be absent" || pass "B: no ollama.pid"
[[ -f "$STATE/ollama.started-by-jobmail" ]] && fail "B: marker must be absent" || pass "B: no marker"
jobmail_pid="$(cat "$STATE/jobmail.pid")"
run_stop
kill -0 "$jobmail_pid" 2>/dev/null && fail "B: uvicorn still alive" || pass "B: uvicorn stopped"
kill -0 "$external_ollama" 2>/dev/null && pass "B: external ollama untouched" || fail "B: external ollama killed!"
kill "$external_ollama" 2>/dev/null
cleanup

[[ "$FAILED" == "0" ]] && { echo "ALL PASS"; exit 0; } || { echo "FAILURES"; exit 1; }
