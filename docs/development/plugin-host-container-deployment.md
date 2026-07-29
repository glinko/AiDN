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
never returned by the Hypervisor API or Plugin Host status views. For a
package-backed Host, the Hypervisor materializes a hex-encoded secret in a
private short-lived directory and bind-mounts that file read-only at
`AIDN_PLUGIN_HOST_ACTIVATION_SECRET_FILE`. The raw secret is not placed in the
Docker command environment. The runtime removes the file and its private
directory when the managed Host exits or is stopped.

A privileged Docker daemon or host operator can still inspect the bind-mounted
source and remains a trusted local boundary. This protects against ordinary
container environment inspection, not against a hostile local administrator.
Legacy built-in Hosts retain the explicit environment delivery path while that
transitional non-package execution mode remains supported.

Run the real acceptance check on a Docker-capable operator host:

```bash
PYTHONPATH=src python tools/plugin_host_container_acceptance.py
```

The harness verifies that the container is non-root, cannot write the mounted
package tree and cannot open an outbound network connection.
