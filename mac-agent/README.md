# mac-agent

Runs on your Mac. Wraps `security find-generic-password` (or the `op` CLI)
behind a local Unix socket.

## Setup

```bash
brew install socat

# store a secret in Keychain with a confirm-ACL (not "always allow"):
security add-generic-password -a "$USER" -s n8n-api-key -w "<token>" -T ""
```

The `-T ""` gives no application blanket access — every read prompts you.
Open Keychain Access.app on the item afterwards to double check it's set to
"Ask for Keychain" / confirm rather than "Allow all applications".

## Run

```bash
KEYHOLE_SOCKET=/tmp/keyhole-agent.sock ./keyhole-agent.sh
```

## Use over SSH

Add the forward to the SSH command you already run to reach the VM:

```bash
ssh -R /run/keyhole.sock:/tmp/keyhole-agent.sock user@vm
```

`/run/keyhole.sock` must already exist as a file on the VM (`touch
/run/keyhole.sock` once) and be bind-mounted into the container at
`docker run` time — see the top-level [architecture doc](../docs/architecture.md).

## 1Password backend

```bash
KEYHOLE_BACKEND=1password ./keyhole-agent.sh
```

Requires the `op` CLI signed in, and per-item "Require Touch ID
confirmation" turned on for the items you want gated.
