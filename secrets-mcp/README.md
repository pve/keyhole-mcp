# secrets-mcp

Runs inside the container. Exposes one MCP tool, `get_secret(name)`, backed
by the Unix socket bind-mounted from the VM host (see the mac-agent side of
[docs/architecture.md](../docs/architecture.md)).

## Install & run

```bash
npm install
KEYHOLE_SOCKET=/run/keyhole.sock node index.js
```

## Register with Claude Code

```bash
claude mcp add keyhole-secrets -- node /path/to/secrets-mcp/index.js
```

(or add it to your MCP client config directly, pointing at `index.js`).

## Environment variables

| Variable             | Default            | Meaning                                   |
|-----------------------|---------------------|--------------------------------------------|
| `KEYHOLE_SOCKET`      | `/run/keyhole.sock` | Path to the bind-mounted socket            |
| `KEYHOLE_TIMEOUT_MS`  | `15000`             | How long to wait for the Mac to respond    |
