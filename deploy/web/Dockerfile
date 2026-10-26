# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS build

ARG SITE_BASE=/
ENV SITE_BASE=${SITE_BASE}

WORKDIR /site
COPY site/package.json site/package-lock.json ./
RUN npm ci
COPY site/ ./
RUN npm run build

FROM caddy:2.10-alpine

COPY deploy/web/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /site/_site /srv

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget --quiet -O /dev/null http://127.0.0.1:2019/config/ || exit 1
