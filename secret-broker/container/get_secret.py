#!/usr/bin/env python3
"""
Client: runs INSIDE the container. Requests a secret from the host daemon
over TCP to host.docker.internal.

No Unix-socket mount: on a local Docker Desktop setup, Docker Desktop's
file-sharing (virtiofs/gRPC-FUSE) does not reliably proxy a bind-mounted
socket live into the container VM. Docker Desktop does forward
host.docker.internal to loopback services on the host, though.

Usage:
    python3 get_secret.py EXAMPLE_API_KEY
    export EXAMPLE_API_KEY=$(python3 get_secret.py EXAMPLE_API_KEY)

Exit codes: 0 = ok (value on stdout), 1 = denied/error (reason on stderr).
"""

from __future__ import annotations

import json
import os
import socket
import sys

BROKER_HOST = os.environ.get("SECRET_BROKER_HOST", "host.docker.internal")
BROKER_PORT = int(os.environ.get("SECRET_BROKER_PORT", "8765"))
TIMEOUT_S = 70  # > host-side approval timeout


def request_secret(name: str) -> tuple[bool, str]:
    payload = {
        "action": "get_secret",
        "name": name,
        "requester": socket.gethostname(),
    }

    try:
        with socket.create_connection((BROKER_HOST, BROKER_PORT), timeout=TIMEOUT_S) as s:
            s.sendall((json.dumps(payload) + "\n").encode("utf-8"))

            data = b""
            while not data.endswith(b"\n"):
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
    except (OSError, socket.timeout) as e:
        return False, f"connection error to {BROKER_HOST}:{BROKER_PORT}: {e} (is the host daemon running?)"

    try:
        resp = json.loads(data.decode("utf-8").strip())
    except ValueError:
        return False, "invalid response from broker"

    if resp.get("status") == "ok":
        return True, resp["value"]
    return False, resp.get("reason", "unknown error")


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: get_secret.py <SECRET_NAME>", file=sys.stderr)
        sys.exit(1)

    ok, value = request_secret(sys.argv[1])
    if not ok:
        print(f"could not get secret: {value}", file=sys.stderr)
        sys.exit(1)

    print(value)


if __name__ == "__main__":
    main()
