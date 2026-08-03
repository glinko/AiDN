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

`filesystem_scope: NONE` and `filesystem_scope: PLUGIN_DATA_ONLY` are
executable today. `PLUGIN_DATA_ONLY` requires a separate operator-controlled
directory and mounts it read-write only at `/var/lib/aidn/plugin-data`; the
verified package tree remains read-only. `network_scope: NONE` uses the direct
no-network launch path. `network_scope: DECLARED_EGRESS` uses a separate
supervisor: the Plugin Host is attached only to a Docker `--internal` network,
while a non-root proxy sidecar is attached to both that network and Docker's
ordinary bridge network. The proxy permits only exact normalized DNS
`host:port` TCP rules and resolves destinations once, accepting only public
addresses. HTTP absolute-form requests and HTTP CONNECT are supported; private
or LAN destinations, wildcard rules, IP-literal rules and other protocols are
not supported. The supervisor removes the proxy container and internal network
on normal exit, signal shutdown, failed startup and failed network attachment.
`PRIVATE_ONLY`, `MODEL_STORAGE_ONLY` and `CONTROLLED_PATHS` remain rejected by
the package Docker launcher. `secret_scope: DECLARED_HANDLES_ONLY` remains
required.

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
package tree, can write only the explicitly mounted plugin-data directory and
cannot open an outbound network connection.

For declared public egress, run the separate Docker acceptance check:

```bash
PYTHONPATH=src python tools/plugin_host_egress_acceptance.py
```

It verifies an allowed public request, a denied destination, blocked direct
network access from the Plugin Host and proxy environment binding. The command
requires a Docker-capable host and may pull the configured `python:3.11-slim`
image. This acceptance does not authorize arbitrary private-network access.
