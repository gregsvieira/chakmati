#!/usr/bin/env bash
# Sets up and runs the local OpenWA server (https://openwa.dev) that lite-agent uses to talk to WhatsApp Web.
#
#   scripts/openwa.sh setup      install OpenWA (+ its own Node.js) into ~/.lite-agent/openwa and create an API key
#   scripts/openwa.sh start      start it with a VISIBLE browser window: scan the QR on first use
#   scripts/openwa.sh start-bg   start it without a window (only after the first login was saved)
#   scripts/openwa.sh stop | status | logs
#
# WARNING: OpenWA automates WhatsApp Web. WhatsApp's terms do not allow this and the linked number can be banned.
# Use a secondary number, keep volumes low, and never leave it exposed beyond 127.0.0.1.
#
# Why the odd steps in `setup` (each one was needed on a real machine, see docs/superpowers/specs):
#  * private npm cache: ~/.npm may hold root-owned files from an old `sudo npm`, which makes `npx` fail with EACCES;
#  * `overrides`: OpenWA 5.1.0 pins effect@4.0.0-beta.100, but npm hoists a stable 4.0.x for one sub-package and the
#    app crashes with ERR_MODULE_NOT_FOUND; both packages are pinned to the same beta;
#  * a local `node@22`: OpenWA needs Node >= 22.21.1 (22.14 lacks zlib.createZstdDecompress). The system Node is NOT touched
#    (other projects may pin an exact Node version).
set -euo pipefail

DIR="${LITEAGENT_OPENWA_HOME:-$HOME/.lite-agent/openwa}"
PORT="${LITEAGENT_OPENWA_PORT:-8081}"
SESSION="${LITEAGENT_OPENWA_SESSION:-lite-agent}"
OPENWA_VERSION="5.1.0"
EFFECT_VERSION="4.0.0-beta.100"
BIN="$DIR/node_modules/.bin"

run_cmd() {  # $1 = extra flags
  [ -x "$BIN/wa-automate" ] || { echo "OpenWA is not installed: run '$0 setup' first" >&2; exit 1; }
  if curl -s -m 2 -o /dev/null "http://127.0.0.1:$PORT/health"; then echo "already running on :$PORT"; exit 0; fi
  mkdir -p "$DIR/run" && cd "$DIR/run"
  # authTimeout: OpenWA gives up 60 s after launch if nobody scanned the QR (fatal error); 15 min is plenty
  # chromiumArgs: a small window, enough for the QR
  [ -f wa.config.json ] || printf '{ "authTimeout": 900, "qrTimeout": 900, "chromiumArgs": ["--window-size=470,760", "--window-position=80,60"] }\n' > wa.config.json
  # shellcheck disable=SC2086
  PATH="$BIN:$PATH" nohup "$BIN/wa-automate" --session-id "$SESSION" --host 127.0.0.1 --port "$PORT" \
      --api-key "$(cat "$DIR/api_key.txt")" --config "$DIR/run/wa.config.json" $1 > "$DIR/openwa.log" 2>&1 &
  echo "started (pid $!). Waiting for it to be ready..."
  for _ in $(seq 1 40); do
    sleep 3
    state=$(curl -s -m 2 "http://127.0.0.1:$PORT/health" | python3 -c 'import sys,json;h=json.load(sys.stdin);print(h["session"]["state"])' 2>/dev/null || echo down)
    echo "  state: $state"
    [ "$state" = "READY" ] && { echo "WhatsApp is linked and ready."; exit 0; }
  done
  echo "Not ready yet. If a window shows a QR code: WhatsApp > Linked devices > Link a device. See '$0 logs'." >&2
}

case "${1:-}" in
  setup)
    command -v node >/dev/null && command -v npm >/dev/null || { echo "Node.js and npm are required" >&2; exit 1; }
    mkdir -p "$DIR" && cd "$DIR"
    export npm_config_cache="$HOME/.lite-agent/npm-cache"
    [ -f package.json ] || npm init -y >/dev/null
    node -e '
      const fs = require("fs"); const p = JSON.parse(fs.readFileSync("package.json"));
      p.dependencies = { ...p.dependencies, "effect": process.argv[1] };
      p.overrides = { "effect": process.argv[1], "@effect/platform-node-shared": process.argv[1] };
      fs.writeFileSync("package.json", JSON.stringify(p, null, 2));' "$EFFECT_VERSION"
    npm install "@open-wa/wa-automate@$OPENWA_VERSION" node@22 --no-audit --no-fund
    if [ ! -f api_key.txt ]; then
      python3 -c 'import secrets;print(secrets.token_urlsafe(24))' > api_key.txt; chmod 600 api_key.txt
    fi
    echo "Installed. Local Node: $("$BIN/node" --version). Next: $0 start"
    ;;
  start)    run_cmd "--headful --qr-timeout 900" ;;
  start-bg) run_cmd "" ;;
  stop)
    pkill -f "wa-automate" || { echo "was not running"; exit 0; }
    # SIGTERM is not always enough (a leftover process keeps the port and a later start says "already running")
    for _ in 1 2 3 4 5 6; do pgrep -f "wa-automate" >/dev/null || break; sleep 1; done
    pgrep -f "wa-automate" >/dev/null && { pkill -9 -f "wa-automate"; sleep 1; }
    echo "stopped" ;;
  status)   curl -s -m 3 "http://127.0.0.1:$PORT/health" | python3 -c 'import sys,json;h=json.load(sys.stdin);print("connected:",h["connected"],"| state:",h["session"]["state"])' 2>/dev/null || echo "not running" ;;
  logs)     tail -n 40 "$DIR/openwa.log" ;;
  *)        sed -n '2,10p' "$0"; exit 2 ;;
esac
