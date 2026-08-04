# MCP TLS Rotation Acceptance

Date: `2026-08-04`

Status: `PASS` for controlled technical host acceptance

## Scope

This run exercised the real production `aidn-mcp-server-http` profile on the
Ubuntu operator host at `192.168.88.127`. It used the host's existing AiDN
virtual environment and a temporary source overlay under `/tmp`; the operator
checkout, production Secret Manager, Registry peers and persistent operator
state were not modified.

The harness generated disposable CA, server and client identities, stored the
server certificate, private key and CA in an encrypted `FileSecretManager`,
started the real MCP HTTP launcher, and connected with a client certificate.
It then atomically rotated the server certificate/key handles and verified the
new listener and session behavior.

## Passed Checks

- real mTLS client certificate authentication;
- Secret Manager-backed certificate, key and CA handles;
- initial server certificate serial matched the materialized Secret Manager value;
- rotated server certificate serial matched the new value;
- graceful single-worker server restart;
- old ephemeral MCP transport session rejected after restart;
- new MCP transport session accepted after reconnect;
- `tools/list` remained available after reconnect;
- temporary source overlay cleanup completed.

The run produced two distinct disposable certificate serials and returned the
machine-readable result `{"status":"ok"}`.

## Reproduction

Once the current checkout is available on the target host:

```bash
./tools/run-remote-mcp-tls-rotation-acceptance.sh \
  --remote-ssh user@192.168.88.127 \
  --remote-repo /home/user/aidn/AiDN
```

The runner uses SSH authentication supplied by the operator, uploads no
production secrets, and creates only a disposable `/tmp` source/test scope.

## Evidence Boundary

This proves protocol and host interoperability under controlled execution. It
does not prove organizational independence, key ownership independence or
public-network trust. The run used one controlling SSH authority and therefore
retains:

```text
ownership_evidence: NOT_PROVEN_BY_PROTOCOL
```
