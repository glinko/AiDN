# Plugin Host Docker Boundary Acceptance

Date: 2026-08-02  
Host: `192.168.88.127`  
Runtime: Ubuntu 24, Docker Server `29.1.3`  
Source: current working tree at the time of the run (`a6267ea` plus the
uncommitted Plugin Host boundary changes)

## Procedure

The current `src/aidn_hypervisor` tree and acceptance tools were copied into a
disposable directory under `/tmp` on the test host. The host checkout was not
modified. The tools were run under the host Docker operator account through
`sudo`; the temporary source directory was removed after the run.

Commands executed from the disposable source tree:

```text
python tools/plugin_host_container_acceptance.py
python tools/plugin_host_egress_acceptance.py
```

## Results

The existing no-network and scoped-data boundary passed:

```json
{"result": {"network_blocked": true, "package_write_blocked": true, "plugin_data_write_allowed": true, "secret_env_absent": true, "secret_file_present": true, "uid": 65534}, "status": "ok"}
```

The declared-egress boundary passed:

```json
{"result": {"allowed_request_succeeded": true, "denied_request_blocked": true, "direct_network_blocked": true, "proxy_configured": true}, "status": "ok"}
```

The post-run Docker resource check found no remaining `aidn-egress-proxy-*`
containers or `aidn-egress-*` networks.

## Boundary Proven

- package files are mounted read-only;
- Plugin Host runs as UID `65534`;
- activation secret is available only through the read-only file mount;
- activation secret is absent from the ordinary environment;
- the explicitly declared plugin-data directory is writable;
- direct Plugin Host network access is blocked;
- declared public HTTP egress succeeds through the proxy;
- an undeclared destination is rejected;
- proxy and internal network resources are cleaned up after execution.

The proxy allowlist accepts exact normalized DNS `host:port` TCP rules and
rejects private or LAN destinations after resolution. This acceptance does not
validate private-network egress, arbitrary protocols or independent operator
ownership. A privileged local Docker operator remains a trusted boundary.
