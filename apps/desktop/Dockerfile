# syntax=docker/dockerfile:1.7
# ============================================================================
# Frontend Dockerfile — Electron renderer served as a static web app via nginx
# ----------------------------------------------------------------------------
# Electron itself cannot run inside a container (it needs a real display
# server + a window manager). What we CAN do is build the Vite renderer bundle
# and serve it as a plain SPA via nginx — that gives us a "headless web mode"
# that is useful for:
#   - Servers with no desktop environment
#   - Browser-only access to the agent UI
#   - The nginx reverse proxy's `frontend` upstream
#
# Stage 1: node:20-alpine + npm ci + npm run build → /app/renderer/dist
# Stage 2: nginx:alpine + copy dist + nginx.conf, EXPOSE 80
# ============================================================================


# ---------------------------------------------------------------------------
# Stage 1 — builder: compile the Vite renderer bundle
# ---------------------------------------------------------------------------
FROM node:20-alpine AS builder

WORKDIR /app

# Copy lockfile + package.json first to maximise the Docker layer cache hit.
# npm ci refuses to run without a package-lock.json, so we fail fast if it
# isn't present (the test suite asserts it exists).
COPY apps/desktop/package.json apps/desktop/package-lock.json ./apps/desktop/

WORKDIR /app/apps/desktop

# `npm ci` installs exactly the versions pinned in package-lock.json (no
# semver drift). --no-audit + --no-fund suppress advisory output that
# would otherwise pollute the build log.
RUN npm ci --no-audit --no-fund

# Copy the rest of the renderer source (tsconfig, vite config, electron/,
# renderer/). The .dockerignore at the repo root filters out
# apps/desktop/node_modules and apps/desktop/renderer/dist so we don't
# overwrite the freshly-installed deps or ship stale build artifacts.
WORKDIR /app
COPY apps/desktop ./apps/desktop

WORKDIR /app/apps/desktop

# Build the renderer bundle. The `build` script chains `tsc -b && vite build`
# so we get a typecheck pass before the actual bundle emission. Output lands
# in renderer/dist/ (per vite.config.ts).
#
# We pass VITE_API_URL as a build-time arg so the bundle can be compiled
# against a specific backend URL. The compose file passes
# VITE_API_URL=http://backend:8765 so the SPA calls the backend by its
# compose-network hostname (resolved via Docker's embedded DNS).
ARG VITE_API_URL=http://backend:8765
ENV VITE_API_URL=${VITE_API_URL}

RUN npm run build


# ---------------------------------------------------------------------------
# Stage 2 — runtime: serve the static bundle via nginx
# ---------------------------------------------------------------------------
FROM nginx:alpine AS runtime

# Drop the default nginx config — we ship our own.
RUN rm -f /etc/nginx/conf.d/default.conf

# Copy the renderer build output to nginx's document root.
COPY --from=builder /app/apps/desktop/renderer/dist /usr/share/nginx/html

# Copy a tiny site-config that:
#   1. serves index.html for all unknown routes (SPA history fallback),
#   2. sets long-lived cache headers for /assets/* (Vite emits hashed names),
#   3. disables caching for index.html so users always get the latest build.
#
# NOTE: this is the *frontend's* own nginx config — NOT the reverse-proxy
# nginx.conf at the repo root. The reverse-proxy nginx.conf forwards
# `/` → frontend:80, which is what this config answers.
COPY apps/desktop/nginx-frontend.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

# nginx:alpine already has a sensible CMD (nginx -g 'daemon off;') — no need
# to override it.
