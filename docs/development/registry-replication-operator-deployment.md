# Registry Replication Operator Deployment

`RegistryReplicationRuntime` is disabled unless
`AIDN_REGISTRY_REPLICATION_CONFIG` names an operator-owned JSON configuration.
It accepts no private key, certificate or peer trust decision from the network.

## Required Trust Inputs

1. Register every peer identity locally through the Registry operator API. The
   configured peer ID must be enabled and its Ed25519 public key must match the
   approved record before an outbound link is created.
2. Store the local Ed25519 signing key, mTLS certificate, mTLS private key and
   CA bundle in the encrypted File Secret Manager under `secret://` handles.
3. Keep the 32-byte File Secret Manager master key outside the repository and
   encrypted state file. Production deployments should source it from an OS
   credential store, KMS agent or injected deployment secret.

The local encrypted secret file is not a replacement for a KMS. It provides a
strict local backend and an injection boundary for an external secret manager.

## Environment

```bash
export AIDN_REGISTRY_REPLICATION_CONFIG=/etc/aidn/registry-replication.json
export AIDN_SECRET_MANAGER_PATH=/var/lib/aidn/secrets.json
export AIDN_SECRET_MANAGER_MASTER_KEY="$(cat /run/secrets/aidn-secret-manager-key-base64)"
```

`AIDN_SECRET_MANAGER_MASTER_KEY` is base64-encoded 32-byte key material. Do
not put it in a systemd unit, shell history, repository, or replication JSON.

## Configuration

The JSON contains transport addresses and opaque handles only:

```json
{
  "local_peer_id": "registry-east-1",
  "signing_key_handle": "secret://registry/east-1/ed25519",
  "listener": {
    "host": "0.0.0.0",
    "port": 9443,
    "tls": {
      "certificate_handle": "secret://registry/east-1/certificate",
      "private_key_handle": "secret://registry/east-1/private-key",
      "certificate_authority_handle": "secret://registry/ca"
    }
  },
  "outbound_peers": [
    {
      "peer_id": "registry-west-1",
      "host": "registry-west-1.example.net",
      "port": 9443,
      "tls": {
        "certificate_handle": "secret://registry/east-1/certificate",
        "private_key_handle": "secret://registry/east-1/private-key",
        "certificate_authority_handle": "secret://registry/ca"
      }
    }
  ],
  "network_id": "aidn",
  "chain_id": "main",
  "network_revision": "1.0"
}
```

The listener requires mTLS and the outbound transport verifies the remote
certificate. A peer that is not already approved locally is rejected before a
socket is opened. Runtime stop invalidates peer authentication and deletes the
temporary mode-0600 TLS files materialized for `ssl.SSLContext`.

## Operational Checks

Start the Hypervisor normally. Its lifespan starts the configured replication
runtime and stops it before process exit. Inspect `app.state.registry_replication_runtime.status()` or the operator runtime view for outbound authentication and sanitized errors. The next acceptance step is to run the same configuration against an independently operated peer; do not treat two processes owned by one operator as independent trust evidence.

## Host-Separated Acceptance Harness

`tools/registry_replication_peer_acceptance.py` creates disposable mTLS and
Ed25519 material, starts a test-only Registry peer, and verifies signed peer
authentication, inventory exchange and immutable object transfer. It is useful
for validating a Linux peer from another host without exposing an operator key:

```bash
# On the peer host.
PYTHONPATH=src python tools/registry_replication_peer_acceptance.py server \
  --state-dir /tmp/aidn-registry-acceptance --port 9443

# Transfer client-bootstrap.json only through an authenticated operator channel,
# then run on the other host. SSH forwarding may be used when the peer binds
# loopback only.
PYTHONPATH=src python tools/registry_replication_peer_acceptance.py client \
  --state-dir /tmp/aidn-registry-client \
  --bundle client-bootstrap.json --host 127.0.0.1 --port 19443
```

The harness is not an operator deployment and its bootstrap bundle is test-only.
It proves transport interoperability, not independent ownership or production
directory trust.
