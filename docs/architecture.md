# Architecture

```
Mac (host)                          SSH (your normal connection,      Linux VM (may be a
                                     plus one extra -R flag)           different host)
┌───────────────┐                                                    ┌──────────────────────────┐
│ mac-agent      │◄─────────────────────────────────────────────────│ sshd (already running)    │
│ listens on:    │   /run/keyhole.sock  <-->  /tmp/keyhole-agent.sock│ AllowStreamLocalForwarding │
│ /tmp/keyhole-  │   (exists only while THIS ssh session is open)    │ StreamLocalBindUnlink yes  │
│ agent.sock     │                                                   └────────────┬───────────────┘
└───────┬────────┘                                                                │ bind-mount
        │ Touch ID / confirm dialog                                               │ (fixed path,
        │ (per secret name, via Keychain                                          │  created once)
        │  ACL or 1Password item setting)                                         ▼
        │                                                              ┌────────────────────┐
        └──────────────────────────────────────────────────────────── │ container            │
                                                                        │  ┌────────────┐      │
                                                                        │  │ Claude Code │      │
                                                                        │  └─────┬──────┘      │
                                                                        │        │ tool call    │
                                                                        │        ▼             │
                                                                        │  ┌────────────┐      │
                                                                        │  │ secrets-mcp │      │
                                                                        │  └─────┬──────┘      │
                                                                        │        ▼             │
                                                                        │  /run/keyhole.sock    │
                                                                        └────────────────────┘
```

## Request flow

1. While building something new, Claude Code calls the `get_secret` tool on
   `secrets-mcp`, e.g. `get_secret("n8n-api-key")`.
2. `secrets-mcp` opens `/run/keyhole.sock` inside the container and writes a
   one-line JSON request: `{"name":"n8n-api-key"}`.
3. That socket is a bind-mount of a path on the VM; if an SSH session is
   currently forwarding it, the request lands on `mac-agent` on your Mac.
4. `mac-agent` runs `security find-generic-password -a "$USER" -s
   n8n-api-key -w` (or the `op` CLI equivalent). Because the Keychain item
   (or 1Password item) is set to **confirm before allowing access** rather
   than "always allow", macOS shows a native Touch ID / password prompt.
5. You approve → the value is written back over the socket as one line of
   JSON → `secrets-mcp` returns it to Claude Code, which sets it as the new
   MCP server's env var and starts it.

## Two independent lifetimes

- **The bind-mount** (`/run/keyhole.sock` inside the container) is created
  once, when the container starts, and persists for the container's whole
  life — independent of whether anyone is connected.
- **The socket forward** (the SSH `-R` flag) exists only while a particular
  SSH session is open. When you disconnect, `get_secret` calls simply fail
  with a clear "no Mac connection" error until you reconnect with the
  forward attached again.
- **The confirm dialog** happens once per secret *name* per Keychain/
  1Password session state — not once per container lifetime, not on every
  single call if the underlying keychain item was left unlocked. Configure
  the item's ACL according to how often you want to be asked; "confirm"
  (not "always allow") is what gives you a prompt on (repeated) access.

## Threat model

What this protects against:

- A compromised or curious process on the VM/container reading a secret out
  of `docker inspect`, `ps`, an env dump, or a leftover file — none of that
  exists; secrets never touch the VM's or the container's disk.
- A secret being fetched without your knowledge — every fetch requires a
  live SSH forward from your Mac plus a Keychain/1Password confirm action.

What this does **not** protect against:

- A compromised process running *inside the container while you are
  connected* — it can call `get_secret` with any name it likes and you may
  approve without knowing what actually asked. `secrets-mcp` should log
  every request (name + timestamp) so you can audit after the fact; it does
  not currently attempt to prove the request's origin.
- A compromised Mac — `mac-agent` has the same trust level as any other
  process reading your Keychain.
- Replay/DoS: nothing currently rate-limits or deduplicates repeated
  requests for the same secret from inside the container.

These are open hardening items, not solved problems — see the issue tracker.
