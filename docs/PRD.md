# PRD: session-start secret grants for MCP servers

Status: draft, MVP scope. Date: 2026-11-09.

## Problem

Coding agents (Claude Code, run under a multiplexer such as herdr) run on a
remote Linux VM while the human sits at a Mac. MCP servers need API keys or
tokens, and almost always need them **when the session starts**, because
Claude Code launches the MCP servers then. Today the choices are bad: keep the
secrets on the VM (a second place to leak from), put them in the environment of
the agent (the agent can read them), or paste them by hand every session.

## Goal

At session start, the human explicitly approves which named secrets each MCP
server gets. Secrets stay on the Mac, travel only on approval, and end up only
in the environment of the one MCP server process that needs them.

## Non-goals (MVP)

- Mid-session, agent-initiated requests (`request_secret`, `run_with_secret`).
  Later, once the start-up path works.
- Offline or unattended approval, push to phone, a relay server.
- Making a compromised VM safe. The threat model is "agent or process on the
  VM must not get secrets I did not approve", not "VM is hostile".
- Secret rotation, sharing between users, a UI beyond a native dialog.

## Assumption on connectivity

MVP assumes a connection exists whenever a secret is needed: the human opens
the session from the Mac and keeps the link up (ssh `-R` today). Without a
connection the launch fails with a clear reason; no queueing, no unattended
approval. Transport (Teleport, outbound HTTPS) is a later concern; the VM side
only sees a Unix socket, so it can change without touching the wrapper.

## Users and stories

1. I start a Claude Code session in a herdr pane. One dialog on my Mac lists
   what is requested ("debian-herdr, ~/proj: server `github` wants GITHUB_TOKEN;
   server `hetzner` wants HETZNER_TOKEN"). I approve all, some, or none.
2. An MCP server whose secrets I denied shows as failed in `/mcp`. Claude sees
   the tools are missing and can adapt; the error says "denied" or "no Mac
   connection", not a generic crash.
3. No connection at launch: the server fails with `no_connection`; nothing
   is released.
4. The agent runs `env` or reads files: it finds no secret values.

## Solution (MVP)

A VM-side wrapper, `keyhole exec`, used as the command in `.mcp.json`:

    "github": { "command": "keyhole", "args": ["exec", "GITHUB_TOKEN", "--", "npx", "github-mcp"] }

Flow:

1. Claude Code spawns `keyhole exec`. It sends the secret names, server label,
   host and working directory to the Mac agent over the socket.
2. The Mac agent checks each name against its own allow-list (`mapping.json`
   name -> Keychain item). Unknown names are refused without a dialog.
3. The agent shows one native dialog. Approval choices: deny, this launch, or
   this session for N hours (so `claude --resume` and herdr restarts do not
   re-prompt). Default is deny; no answer in 60 s is deny.
4. On approval the agent reads the values from the macOS Keychain and returns
   them. `keyhole exec` starts the real server with the values added to **that
   process's** environment only (`exec`, no shell, nothing written to disk).
5. On denial or timeout it exits non-zero with a one-line reason on stderr.

Concurrent launches within a short window (about 2 s) are batched into one
dialog by the agent.

Reuse from this repo: `mac-agent` (socket, Keychain lookup) is extended with
the allow-list, the dialog and batching. `secrets-mcp` is not needed for the
MVP; the wrapper replaces it.

## Requirements

- R1. Secrets never touch the VM disk and never enter the environment of the
  agent process or the herdr server.
- R2. Names not in the Mac-side allow-list are never released, whatever the
  VM-side manifest says. The VM cannot add a name.
- R3. Default deny, with timeout. Dialog text is shown as "claimed by the
  requester", not as proof.
- R4. Every request (names, label, host, cwd, decision, time) is logged on the
  Mac, never the values.
- R5. Failure messages distinguish `denied`, `timeout`, `no_connection`,
  `unknown_name`.
- R6. Grants with a duration are held in agent memory only and expire.

## Known limits

- Any process on the VM that can reach the socket can ask. It still needs the
  human to approve, and can only ask for allow-listed names. The dialog shows
  self-reported context. A socket with file permissions limits who can try.
- An MCP server can leak its own secret (logs, tool output). Scrubbing is out
  of scope.
- A compromised Mac is out of scope.
- A session grant means a process that can launch `keyhole exec` during the
  grant window gets the secret without a new dialog. Keep default durations
  short.

## Success criteria

- A fresh herdr/Claude Code session with two MCP servers starts after one
  dialog, and `env` in the agent shows neither secret.
- Deny and timeout both leave the session usable, with the affected servers
  failed and a readable reason.
- Without a connection, a launch fails cleanly and releases nothing.

## Open questions

1. Does herdr (`--remote`, saved machines) carry an ssh `RemoteForward`? Test
   on the Debian VM with a dummy secret.
2. HTTP MCP servers: does Claude Code's `headersHelper` option fit as the
   same wrapper? Verify in the docs before relying on it.
3. Touch ID instead of a plain dialog: Keychain ACL confirm (as in the
   current prototype) or a LocalAuthentication check in the agent?
4. Default grant duration (proposal: this launch only, with an opt-in 4 h).

## Milestones

1. Mac agent: allow-list, dialog, batching, log. Test with a dummy value.
2. `keyhole exec` wrapper, tested with one stdio MCP server on the VM.
3. End-to-end under herdr with two servers; test deny, timeout, resume.
4. Later: mid-session tools, HTTP MCP, a second transport (Teleport or
   outbound HTTPS), unattended restarts.
