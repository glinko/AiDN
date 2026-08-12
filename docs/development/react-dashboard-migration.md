# React Dashboard Migration

## Status

The React dashboard is an incremental replacement of the static operator shell.
It implements the first UI-0001 vertical slice:

- persistent Hypervisor context and compact navigation;
- Overview with live resource, readiness, Bundle and Endpoint state;
- Bundle inventory;
- Endpoint inventory;
- responsive mobile navigation and an always-visible resource footer.

The existing dashboard remains available at `/operators/dashboard` until all
operator workspaces have functional parity. The React preview is deliberately a
separate route:

`/operators/dashboard/react`

This prevents a partially migrated UI from hiding existing operational flows.

## Architecture

`web/operator-dashboard` is a TypeScript React/Vite package. It owns rendering,
client-side query caching and local view state only. FastAPI remains the sole
owner of Hypervisor state, authorization and operator mutations.

The reference implementation uses:

- React and Vite;
- Tailwind CSS and shadcn/ui primitives;
- TanStack Query for independently fault-tolerant read models;
- TanStack Table for dense Bundle and Endpoint tables;
- Zustand for local workspace state;
- Zod at the API boundary;
- Lucide icons and bundled Manrope/IBM Plex Mono fonts.

The first slice intentionally does not invent timeseries. Recharts is included
for the future telemetry history view, but the current resource cards display
only observations returned by the Hypervisor.

## Local Development

Install the JavaScript dependencies once:

```powershell
cd web/operator-dashboard
pnpm install --frozen-lockfile
```

Run the UI against a local Hypervisor:

```powershell
pnpm dev
```

To use another LAN node, set the Vite proxy target before starting the server:

```powershell
$env:AIDN_HYPERVISOR_URL = 'http://192.168.88.127:8000'
pnpm dev
```

On Linux the equivalent is:

```bash
AIDN_HYPERVISOR_URL=http://192.168.88.127:8000 pnpm dev
```

The Vite base route is `/operators/dashboard/react/`, so open:

`http://127.0.0.1:5173/operators/dashboard/react/`

## Release Packaging

`tools/lan-testnet.Dockerfile` uses a Node build stage to create the Vite
assets. The Python release stage copies them into:

`aidn_hypervisor/static/react-dashboard`

FastAPI serves an unhashed HTML entry with `Cache-Control: no-store` and only
serves regular files below that asset directory. Hashed assets receive immutable
cache headers. The resolver rejects absolute paths, parent traversal and paths
escaping through a symlink.

The package-data declaration includes the built entry point and assets so a
wheel created from the release image retains the dashboard.

## Existing Docker Deployments

For an existing host-network Hypervisor container, use the reviewed rollout
script rather than reconstructing its Docker invocation by hand:

```bash
sudo bash tools/rollout-operator-dashboard-ubuntu.sh \
  --repo /home/user/aidn-dashboard-build-52aa94b \
  --commit <reviewed-commit>
```

The script verifies the expected `aidn-g5-abci` topology, preserves its
`/state` bind mount and AiDN runtime environment, keeps the previous container
as a stopped rollback target, and restores it automatically if health,
consensus, or React asset checks fail.

## API Contract

The React slice consumes only existing read endpoints:

- `GET /operators/dashboard/home`
- `GET /operators/dashboard/readiness`
- `GET /operators/dashboard/fleet`
- `GET /operators/dashboard/bundles`
- `GET /operators/dashboard/endpoints`

Each read model has its own TanStack Query. A timeout, malformed response or
server error is shown inside its corresponding panel and cannot leave the whole
dashboard indefinitely loading.

The Bundle workspace now uses the existing read models as a real operator
surface: lifecycle/provider/Endpoint filters, immutable revision inspection,
field-level comparison, and a read-only activation preflight are implemented.
The preflight deliberately reports missing evidence as `unknown` or `blocked`;
it is not a replacement for the planned canonical server-side evidence endpoint.

## Migration Order

1. Overview, Readiness, Bundles and Endpoints.
2. Wallet and settlement workspace.
3. Provider install, model discovery and Runtime Binding workflow.
4. Market, remote endpoints, agents and sessions.
5. Advanced infrastructure, validation and logs.
6. Make the React shell the default after keyboard, accessibility and operator
   workflow parity acceptance.

Every migrated workspace must retain one canonical page per UI-0001 object and
must use real API state. The legacy route may only be removed after all current
operator actions have a tested React equivalent.

## Verification

```powershell
cd web/operator-dashboard
pnpm typecheck
pnpm lint
pnpm build

cd ../..
python -m pytest -o addopts='' tests/test_react_dashboard_assets.py -q
```
