# keyhole-mcp

On-demand secrets for a remote dev container, gated by a Touch ID / Keychain
confirmation on your Mac — nothing lands on the remote host in plaintext,
and no secret exists before it's actually requested.

## Problem

You run Claude Code (and its MCP servers) inside a container on a Linux VM —
often a different physical host, reached over SSH. New MCP servers need new
API keys/tokens as you build. Options considered and rejected:

- Bake secrets into the container image or env at launch → static, over-scoped,
  visible in `docker inspect`/`ps`, and you'd need to know every secret up front.
- Copy secrets onto the VM (`pass`, `systemd-creds`, plain files) → the secret
  now has a second home to leak from.

## Idea

Keep every secret on the Mac, in Keychain or 1Password, with **per-item
confirm-before-release** turned on. Expose a `get_secret` tool to Claude Code
via a small MCP server running inside the container. That MCP server talks to
a Unix socket that is bind-mounted into the container once, at `docker run`
time. The socket only has a live peer on the Mac side when you're actually
SSH'd into the VM — you add one extra flag to the SSH command you're already
running:

```
ssh -R /run/keyhole.sock:/tmp/keyhole-agent.sock user@vm
```

No standalone tunnel daemon, no open port, no standing bridge when nobody's
connected. See [docs/architecture.md](docs/architecture.md) for the full
diagram and request flow.

## Components

- **[mac-agent/](mac-agent/)** — runs on your Mac. Listens on a local Unix
  socket, looks up a named secret via `security find-generic-password`
  (macOS Keychain) or the `op` CLI (1Password), and returns it. The
  Keychain/1Password confirm-ACL is what actually shows you the Touch ID
  prompt — this script has no dialog logic of its own.
- **[secrets-mcp/](secrets-mcp/)** — runs inside the remote container. A
  minimal MCP server exposing one tool, `get_secret(name)`, that forwards
  the request over the bind-mounted socket and returns the value (or a clear
  "no Mac connection right now" error if nobody is currently SSH'd in with
  the forward attached).

## Status

Early prototype. The socket protocol is intentionally dumb (newline-delimited
JSON request/response) so it's easy to reimplement the agent side in
something other than bash if needed. Not yet hardened: see
[docs/architecture.md#threat-model](docs/architecture.md#threat-model) for
what this does and does not protect against today.

## License

MIT — see [LICENSE](LICENSE).
