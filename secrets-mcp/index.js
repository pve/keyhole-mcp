#!/usr/bin/env node
// keyhole-secrets-mcp: exposes one tool, get_secret(name), to whatever MCP
// client (e.g. Claude Code) is running inside this container. Every call is
// forwarded over a Unix socket that is only "live" while a Mac is currently
// SSH'd in with the matching -R forward attached — see docs/architecture.md
// in the repo root for the full picture.

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import net from "node:net";

const SOCKET_PATH = process.env.KEYHOLE_SOCKET ?? "/run/keyhole.sock";
const REQUEST_TIMEOUT_MS = Number(process.env.KEYHOLE_TIMEOUT_MS ?? 15000);

function requestSecret(name) {
  return new Promise((resolve, reject) => {
    const socket = net.createConnection(SOCKET_PATH);
    let buffer = "";
    let settled = false;

    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      socket.destroy();
      reject(
        new Error(
          "no response from mac-agent within timeout — is the Mac currently " +
            "SSH'd in with the socket forward attached?"
        )
      );
    }, REQUEST_TIMEOUT_MS);

    socket.on("connect", () => {
      socket.write(JSON.stringify({ name }) + "\n");
    });

    socket.on("data", (chunk) => {
      buffer += chunk.toString("utf8");
      const newlineIndex = buffer.indexOf("\n");
      if (newlineIndex === -1) return;
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      socket.end();
      try {
        const parsed = JSON.parse(buffer.slice(0, newlineIndex));
        if (parsed.ok) {
          resolve(parsed.value);
        } else {
          reject(new Error(parsed.error ?? "denied"));
        }
      } catch (err) {
        reject(new Error(`malformed response from mac-agent: ${err.message}`));
      }
    });

    socket.on("error", (err) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (err.code === "ENOENT" || err.code === "ECONNREFUSED") {
        reject(
          new Error(
            "no Mac connection right now — connect over SSH with the " +
              "keyhole socket forward and try again"
          )
        );
      } else {
        reject(err);
      }
    });
  });
}

const server = new Server(
  { name: "keyhole-secrets-mcp", version: "0.1.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "get_secret",
      description:
        "Fetch a named secret from the operator's Mac Keychain/1Password, " +
        "gated by a Touch ID / confirm dialog on the Mac. Only works while " +
        "the operator has an active SSH session forwarding the keyhole " +
        "socket. Use this instead of asking the user to paste a credential " +
        "when wiring up a new MCP server or integration.",
      inputSchema: {
        type: "object",
        properties: {
          name: {
            type: "string",
            description:
              "Secret identifier, matching the Keychain 'service' name or " +
              "1Password item name on the operator's Mac.",
          },
        },
        required: ["name"],
      },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  if (request.params.name !== "get_secret") {
    throw new Error(`unknown tool: ${request.params.name}`);
  }
  const { name } = request.params.arguments ?? {};
  if (typeof name !== "string" || name.length === 0) {
    throw new Error("get_secret requires a non-empty 'name' argument");
  }

  try {
    const value = await requestSecret(name);
    return { content: [{ type: "text", text: value }] };
  } catch (err) {
    return {
      content: [{ type: "text", text: `Error: ${err.message}` }],
      isError: true,
    };
  }
});

const transport = new StdioServerTransport();
await server.connect(transport);
