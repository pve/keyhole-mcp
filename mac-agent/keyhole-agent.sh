#!/usr/bin/env bash
# keyhole-agent: listens on a local Unix socket, resolves a secret name to a
# value via macOS Keychain (or 1Password, if KEYHOLE_BACKEND=1password), and
# writes the value back as one line of JSON.
#
# Protocol (newline-delimited JSON, one request/response per connection):
#   -> {"name":"n8n-api-key"}
#   <- {"ok":true,"value":"..."}
#   <- {"ok":false,"error":"not found"}
#
# The Touch ID / confirm dialog is NOT drawn by this script — it comes from
# the Keychain item's own ACL ("confirm before allowing access" instead of
# "always allow"), or from 1Password's per-item "Require Touch ID" setting.
# This script only shells out; the OS/app owns the prompt.
#
# Requires: socat (brew install socat)

set -euo pipefail

SOCKET_PATH="${KEYHOLE_SOCKET:-/tmp/keyhole-agent.sock}"
BACKEND="${KEYHOLE_BACKEND:-keychain}"   # keychain | 1password
KEYCHAIN_ACCOUNT="${KEYHOLE_ACCOUNT:-$USER}"
LOG_FILE="${KEYHOLE_LOG:-/tmp/keyhole-agent.log}"

log() { printf '[keyhole-agent] %s\n' "$*" >>"$LOG_FILE"; }

resolve_secret() {
  local name="$1"
  case "$BACKEND" in
    keychain)
      security find-generic-password -a "$KEYCHAIN_ACCOUNT" -s "$name" -w 2>/dev/null
      ;;
    1password)
      op read "op://Private/${name}/credential" 2>/dev/null
      ;;
    *)
      log "unknown backend: $BACKEND"
      return 1
      ;;
  esac
}

handle_one_request() {
  # Called by socat with the client connection on stdin/stdout.
  local line name value
  read -r line || exit 0
  name="$(printf '%s' "$line" | sed -n 's/.*"name" *: *"\([^"]*\)".*/\1/p')"

  if [[ -z "$name" ]]; then
    printf '{"ok":false,"error":"malformed request"}\n'
    exit 0
  fi

  log "request for secret: $name"

  if value="$(resolve_secret "$name")"; then
    # naive JSON string escaping (backslash + double-quote only — good
    # enough for tokens/API keys, not a general JSON encoder)
    value="${value//\\/\\\\}"
    value="${value//\"/\\\"}"
    printf '{"ok":true,"value":"%s"}\n' "$value"
    log "released: $name"
  else
    printf '{"ok":false,"error":"not found or denied"}\n'
    log "denied or missing: $name"
  fi
}

if [[ "${1:-}" == "--handle-one" ]]; then
  handle_one_request
  exit 0
fi

command -v socat >/dev/null 2>&1 || { echo "socat not found — brew install socat" >&2; exit 1; }

rm -f "$SOCKET_PATH"
log "listening on $SOCKET_PATH (backend: $BACKEND)"
exec socat UNIX-LISTEN:"$SOCKET_PATH",fork EXEC:"$0 --handle-one"
