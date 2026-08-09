# AiDN Operator Dashboard

React/Vite reference implementation for the UI-0001 Hypervisor dashboard.

```bash
pnpm install --frozen-lockfile
pnpm dev
```

Set `AIDN_HYPERVISOR_URL` before `pnpm dev` to proxy the dashboard API to a LAN
node. Production assets are built with `pnpm build` and served by FastAPI at
`/operators/dashboard/react`.

See [React Dashboard Migration](../../docs/development/react-dashboard-migration.md)
for architecture, release packaging, and the staged migration plan.
