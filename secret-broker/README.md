# secret-broker

A host daemon + container client pair for the same problem this repo
solves — on-demand secrets, gated by human approval, nothing landing on the
remote/container side until actually requested. Contributed as a variant for
a **local Docker Desktop setup with no remote VM/SSH hop** (no
`ssh -R .../keyhole.sock` in the picture), where the Unix-socket approach
used by [`mac-agent/`](../mac-agent/) + [`secrets-mcp/`](../secrets-mcp/)
runs into a Docker Desktop limitation (see "Why TCP, not a Unix socket"
below).

Also differs in one design choice: approval is an explicit dialog drawn by
the host daemon itself (`osascript`, default-deny, 60s timeout = auto-deny),
rather than relying on a Keychain item's own "confirm before allowing
access" ACL / Touch ID. That means it works even for Keychain items without
a per-item confirm-ACL set, and the prompt shows which container asked for
which secret — but it's an extra moving part instead of letting the OS own
the prompt. Both are valid trade-offs; which one fits depends on whether
you've set per-item Keychain ACLs already.

## Why TCP, not a Unix socket

First attempt bind-mounted a Unix socket into the container, like
`mac-agent/` does. On a **local** Docker Desktop install (Mac and
container on the same machine, connected directly — not over an SSH `-R`
tunnel to a remote VM), that broke: Docker Desktop's file-sharing
(virtiofs/gRPC-FUSE) does not reliably proxy a live Unix socket into the
container VM. A container that bind-mounts the socket's directory sees an
empty, stale directory snapshot instead of the real socket file — `connect
ENOENT`, even though `ls` on the host shows the socket right there.

This is specific to Docker Desktop's local file-sharing layer. It doesn't
affect `mac-agent/`'s actual design here: when the socket file is created
*on the remote VM's own filesystem* by `ssh -R`, Docker's bind-mount on
that VM is a normal same-host bind-mount — no cross-VM proxying involved,
so it doesn't hit this issue.

The fix for the local case: the daemon listens on TCP `127.0.0.1:<port>`
instead, and the container connects to `host.docker.internal:<port>`.
Docker Desktop forwards `host.docker.internal` to loopback services on the
host reliably (documented behavior, not a workaround) — this also happens
to make the same client code portable to Windows Docker Desktop, which
forwards `host.docker.internal` the same way but has no Keychain/`security`
equivalent (would need a Windows-specific daemon backend — not yet built).

## Components

- **`host/secret_broker_host.py`** — daemon, runs on the Mac. TCP server,
  `osascript` approval dialog, macOS Keychain lookup
  (`security find-generic-password`, account always `$USER` — same
  convention as `mac-agent/`).
- **`host/mapping.example.json`** — secret name -> Keychain service name.
  Only names listed here are ever requestable; copy to `mapping.json` and
  fill in (gitignored, keep real names out of git).
- **`container/get_secret.py`** / **`container/get_secret.js`** — client,
  runs inside the container, talks to the daemon over TCP. Two variants
  since not every base image ships `python3` (e.g. a plain `node` image).

## Setup

```bash
# 1. Put the secret in Keychain (on the host)
security add-generic-password -U -a "$USER" -s "<service-name>" -w

# 2. Mapping
cd secret-broker/host
cp mapping.example.json mapping.json
# edit: secret-name -> service-name

# 3. Run the daemon (keep this terminal open)
uv run secret_broker_host.py --mapping mapping.json
# listens on 127.0.0.1:8765 by default (--host/--port to override)

# 4. Container
docker run -it --add-host=host.docker.internal:host-gateway <image> bash
# --add-host is needed on Linux Docker; Docker Desktop (macOS/Windows)
# already resolves host.docker.internal, the flag is a no-op there.

# 5. Inside the container
python3 secret-broker/container/get_secret.py EXAMPLE_API_KEY
# or: node secret-broker/container/get_secret.js EXAMPLE_API_KEY
```

Blocks until the dialog is approved/denied on the host, or times out (60s,
fails closed).

## Security boundaries

- Only names present in `mapping.json` are ever requestable — an unlisted
  name is denied without the human ever seeing a dialog.
- Every request needs a fresh approval; no caching or batch-approve at this
  layer. A long-lived container can cache the *value* itself after one
  approval (e.g. write it to a tmpfs path inside the container on first
  fetch, source it on later commands, drop it when the container is
  removed) — but the daemon itself never remembers a decision.
- Dialog timeout = auto-deny (fail closed, not fail open).
- Daemon binds to `127.0.0.1` — reachable only from the same Mac (directly,
  or via Docker Desktop's `host.docker.internal` forwarding for containers
  on that same Mac), not from the network. Anyone with shell access to the
  host already has Keychain access; this protects against a
  compromised/malicious container, not a malicious host user.

## Status

Prototype, ported from a sibling project where it's been running real
evaluation-pipeline containers. Not yet wired into an MCP tool the way
`secrets-mcp/` is — `get_secret.py`/`.js` are plain CLI clients today. Open
question for review: does it make sense to have `secrets-mcp/`'s
`get_secret(name)` tool support this TCP transport as an alternative
backend (env-var-selected), so there's one MCP tool surface regardless of
which host-agent variant is running?
