# Multi-stage: the runtime image carries the compiled app and production dependencies only (no dev tooling,
# no source, no build caches) and runs as an unprivileged user.

FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:20-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# NEXT_PUBLIC_* values are inlined at build time. The API address server components use (resolvable on the
# Docker network), the one the browser uses, and the canonical site origin (canonical links, Open Graph, sitemap).
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_BROWSER_API_URL
ENV NEXT_PUBLIC_BROWSER_API_URL=$NEXT_PUBLIC_BROWSER_API_URL
ARG NEXT_PUBLIC_SITE_URL
ENV NEXT_PUBLIC_SITE_URL=$NEXT_PUBLIC_SITE_URL
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-alpine AS prod-deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force

FROM node:20-alpine AS run
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
# Security fixes since the base image was built, then drop the package managers: the running server needs only
# `node`, and npm/yarn bundle their own (vulnerable-by-default) copies of tar, glob, cross-spawn, ...
RUN apk upgrade --no-cache     && rm -rf /usr/local/lib/node_modules/npm /usr/local/bin/npm /usr/local/bin/npx /opt/yarn-* /usr/local/bin/yarn /usr/local/bin/yarnpkg
COPY --from=prod-deps --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/.next ./.next
COPY --from=build --chown=node:node /app/public ./public
COPY --from=build --chown=node:node /app/package.json /app/next.config.mjs ./

USER node
EXPOSE 3000

# A cheap route that does not call the API: the web server's own health, not the whole stack's.
HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=3 \
    CMD wget -qO /dev/null http://127.0.0.1:3000/robots.txt || exit 1

CMD ["node", "node_modules/next/dist/bin/next", "start"]
