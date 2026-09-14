#!/usr/bin/env node
// Client for inside the container — Node variant, no python3 dependency
// needed (e.g. a plain node:22 image doesn't guarantee python3).
//
// Talks over TCP to the host daemon at host.docker.internal — no
// Unix-socket mount: on a local Docker Desktop setup, Docker Desktop's
// file-sharing (virtiofs/gRPC-FUSE) does not reliably proxy a bind-mounted
// socket live into the container VM. Docker Desktop does forward
// host.docker.internal to loopback services on the host, though.
//
// Usage: node get_secret.js EXAMPLE_API_KEY
// Exit 0 + value on stdout on success; exit 1 + reason on stderr otherwise.

"use strict";
const net = require("net");
const os = require("os");

const BROKER_HOST = process.env.SECRET_BROKER_HOST || "host.docker.internal";
const BROKER_PORT = Number(process.env.SECRET_BROKER_PORT || 8765);
const TIMEOUT_MS = 70_000; // > host-side approval timeout (60s)

const name = process.argv[2];
if (!name) {
  console.error("usage: get_secret.js <SECRET_NAME>");
  process.exit(1);
}

const client = net.createConnection({ host: BROKER_HOST, port: BROKER_PORT });
let data = "";

client.setTimeout(TIMEOUT_MS);

client.on("connect", () => {
  client.write(JSON.stringify({ action: "get_secret", name, requester: os.hostname() }) + "\n");
});

client.on("data", (chunk) => {
  data += chunk.toString("utf8");
  if (data.includes("\n")) client.end();
});

client.on("timeout", () => {
  console.error("timeout: no response from broker");
  client.destroy();
  process.exit(1);
});

client.on("error", (err) => {
  console.error(`connection error to ${BROKER_HOST}:${BROKER_PORT}: ${err.message} (is the host daemon running?)`);
  process.exit(1);
});

client.on("close", () => {
  if (!data.trim()) return; // error/timeout path already called process.exit(1)
  let resp;
  try {
    resp = JSON.parse(data.trim());
  } catch {
    console.error("invalid response from broker");
    process.exit(1);
  }
  if (resp.status === "ok") {
    process.stdout.write(resp.value + "\n");
    process.exit(0);
  }
  console.error(`could not get secret: ${resp.reason || "unknown error"}`);
  process.exit(1);
});
