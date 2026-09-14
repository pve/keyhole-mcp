#!/usr/bin/env python3
"""
Host daemon: listens on TCP 127.0.0.1:<port>, asks for human-in-the-loop
approval via a macOS dialog (osascript) for every secret request, and on
approve fetches the secret from the macOS Keychain.

Run on the host, NOT inside the container:
    uv run secret_broker_host.py --mapping mapping.json

Keychain convention: account (-a) is always $USER, never the secret name.
mapping.json maps secret name -> Keychain service name (kebab-case); the
daemon fills in -a itself via getpass.getuser().

Loopback-only (127.0.0.1), not a Unix socket: on a local Docker Desktop
setup (no SSH -R tunnel to a remote VM — see the top-level README for how
this relates to mac-agent/), Docker Desktop's file-sharing (virtiofs/gRPC-FUSE)
does not reliably proxy a bind-mounted Unix socket live into the container
VM — a container that bind-mounts a socket file created after the mount
started sees an empty, stale directory snapshot instead of the real socket.
Docker Desktop does forward host.docker.internal to loopback services on the
host, though, which is what the container side (get_secret.js/.py) connects
to.
"""

from __future__ import annotations

import argparse
import getpass
import json
import socket
import socketserver
import subprocess
import sys
import time

APPROVAL_TIMEOUT_S = 60
KEYCHAIN_ACCOUNT = getpass.getuser()  # convention: -a is always $USER, never the service name


def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    print(f"[{ts}] {msg}", file=sys.stderr, flush=True)


def load_mapping(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _applescript_escape(s: str) -> str:
    """Escape a string for safe interpolation into an AppleScript string
    literal. `requester` comes straight from the container's JSON request
    and is not otherwise validated — without this, a crafted requester
    value containing a `"` could break out of the `display dialog` string
    and inject arbitrary AppleScript (including `do shell script`) into the
    osascript invocation below."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def ask_human(secret_name: str, requester: str) -> bool:
    """macOS dialog, default = Deny, timeout = auto-deny (fail closed)."""
    safe_name = _applescript_escape(secret_name)
    safe_requester = _applescript_escape(requester)
    prompt = (
        f'Container ({safe_requester}) is requesting secret \\"{safe_name}\\".\n'
        f"Allow?"
    )
    script = (
        f'display dialog "{prompt}" '
        f'buttons {{"Deny", "Approve"}} default button "Deny" '
        f'with icon caution giving up after {APPROVAL_TIMEOUT_S} '
        f'with title "secret-broker approval"'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=APPROVAL_TIMEOUT_S + 5,
        )
    except subprocess.TimeoutExpired:
        log(f"dialog hard-timed-out for '{secret_name}' -> deny")
        return False

    out = result.stdout.strip()
    # osascript returns: "button returned:Approve, gave up:false"
    approved = "button returned:Approve" in out and "gave up:true" not in out
    log(f"dialog result for '{secret_name}': {out!r} -> {'approve' if approved else 'deny'}")
    return approved


def fetch_from_keychain(service: str) -> str | None:
    result = subprocess.run(
        ["security", "find-generic-password", "-a", KEYCHAIN_ACCOUNT, "-s", service, "-w"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log(f"keychain lookup failed for service={service} (account={KEYCHAIN_ACCOUNT}): {result.stderr.strip()}")
        return None
    return result.stdout.rstrip("\n")


class Handler(socketserver.BaseRequestHandler):
    mapping: dict = {}

    def handle(self) -> None:
        data = b""
        self.request.settimeout(5)
        try:
            while not data.endswith(b"\n"):
                chunk = self.request.recv(4096)
                if not chunk:
                    break
                data += chunk
        except socket.timeout:
            pass

        try:
            req = json.loads(data.decode("utf-8").strip())
        except (ValueError, UnicodeDecodeError):
            self._respond({"status": "error", "reason": "invalid_json"})
            return

        if req.get("action") != "get_secret":
            self._respond({"status": "error", "reason": "unknown_action"})
            return

        name = req.get("name", "")
        requester = req.get("requester", "unknown-container")

        service = self.mapping.get(name)
        if service is None:
            log(f"unknown secret '{name}' requested by {requester} -> denied (not in mapping)")
            self._respond({"status": "denied", "reason": "not_in_mapping"})
            return

        log(f"secret '{name}' requested by {requester} -> asking human")
        if not ask_human(name, requester):
            self._respond({"status": "denied", "reason": "human_denied"})
            return

        value = fetch_from_keychain(service)
        if value is None:
            self._respond({"status": "error", "reason": "keychain_lookup_failed"})
            return

        log(f"secret '{name}' released to {requester}")
        self._respond({"status": "ok", "value": value})

    def _respond(self, payload: dict) -> None:
        self.request.sendall((json.dumps(payload) + "\n").encode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--mapping", default="./mapping.json")
    args = parser.parse_args()

    mapping = load_mapping(args.mapping)
    Handler.mapping = mapping

    server = socketserver.ThreadingTCPServer((args.host, args.port), Handler)

    log(f"secret-broker listening on {args.host}:{args.port}, {len(mapping)} secret(s) in mapping")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
