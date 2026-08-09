FROM node:22-alpine AS operator_dashboard_build

WORKDIR /dashboard
RUN corepack enable
COPY web/operator-dashboard/package.json web/operator-dashboard/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/operator-dashboard/ ./
RUN pnpm build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY --from=operator_dashboard_build /dashboard/dist ./src/aidn_hypervisor/static/react-dashboard
RUN python -m pip install --no-cache-dir .

CMD ["python", "-m", "uvicorn", "aidn_hypervisor.main:build_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
