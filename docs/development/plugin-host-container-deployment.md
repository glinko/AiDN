# Plugin Host Container Deployment

Package-backed Plugin Hosts are launched only when their signed release declares
`SANDBOX_REQUIRED`. `UNSANDBOXED_HOST` is intentionally rejected.

The current Docker backend requires the `python:3.11-slim` image (or an
operator-supplied compatible image) and applies these boundaries:

- verified package tree mounted read-only at `/opt/aidn/plugin`;
- non-root UID `65534`;
- read-only container root, bounded PID count and memory;
- all Linux capabilities dropped and `no-new-privileges` enabled;
- no network and only a bounded `tmpfs` at `/tmp`.

Only `filesystem_scope: NONE`, `network_scope: NONE` and
`secret_scope: DECLARED_HANDLES_ONLY` are executable today. Every other policy
is rejected before `docker run` is invoked.

Activation credentials can use the configured File Secret Manager and are
never returned by the Hypervisor API or Plugin Host status views. The Docker
backend currently forwards the credential as a process environment variable
to the container because the Host handshake needs it. A privileged Docker or
host operator can inspect such a process and remains a trusted local boundary.
Do not treat this as protection from the local operator; secret-file delivery
is required before supporting less-trusted local administration.

Run the real acceptance check on a Docker-capable operator host:

```bash
PYTHONPATH=src python tools/plugin_host_container_acceptance.py
```

The harness verifies that the container is non-root, cannot write the mounted
package tree and cannot open an outbound network connection.
