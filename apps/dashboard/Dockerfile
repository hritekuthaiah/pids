# syntax=docker/dockerfile:1.7
# PIDS control-room console: the production build served by nginx, which also proxies
# /api and /ws to the API — same origin, no CORS, exactly like the Vite dev proxy.
# Build context: repository root (pnpm workspace).

FROM node:24.22.0-alpine AS build
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@10.34.7 --activate
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
COPY packages/api-client/package.json packages/api-client/
COPY apps/dashboard/package.json apps/dashboard/
COPY apps/guard/package.json apps/guard/
RUN --mount=type=cache,id=pnpm,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile --filter "@pids/dashboard..."
COPY packages/api-client packages/api-client
COPY apps/dashboard apps/dashboard
RUN pnpm --filter @pids/dashboard build

FROM nginx:1.30.6-alpine-slim AS runtime
COPY apps/dashboard/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/apps/dashboard/dist /usr/share/nginx/html
HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD ["wget", "-qO-", "http://127.0.0.1:8080/healthz"]
EXPOSE 8080
