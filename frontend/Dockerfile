# syntax=docker/dockerfile:1

# -----------------------------------------------------------------------------
# Stage 1 — build the static SPA with Vite.
#
# NOTE: Vite inlines all VITE_* environment variables at BUILD time. They are
# baked into the generated JS bundle and CANNOT be changed at container runtime.
# To point the app at a different API, you must rebuild with the desired values:
#
#   docker build \
#     --build-arg VITE_API_URL=https://api.example.com \
#     --build-arg VITE_WS_URL=wss://api.example.com \
#     -t fleet-watch-frontend .
# -----------------------------------------------------------------------------
FROM node:20-alpine AS build

WORKDIR /app

# Build-time public config (baked into the bundle — see note above).
ARG VITE_API_URL
ARG VITE_WS_URL
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_WS_URL=$VITE_WS_URL

# Install dependencies against the committed lockfile for reproducible builds.
COPY package.json package-lock.json ./
RUN npm ci

# Copy the rest of the source and build.
COPY . .
RUN npm run build

# -----------------------------------------------------------------------------
# Stage 2 — serve the built assets with nginx.
# -----------------------------------------------------------------------------
FROM nginx:alpine AS runtime

# Bind the platform-provided $PORT (Railway/Render set it); default to 8080 for
# local `docker run`. The nginx:alpine entrypoint renders any file in
# /etc/nginx/templates/*.template through envsubst into /etc/nginx/conf.d/ at
# startup, substituting ${PORT} into the listen directives.
ENV PORT=8080

# CSP connect-src API origin (and websocket origin), substituted into nginx.conf
# at startup. Override at runtime (-e API_ORIGIN=https://api.your-host
# -e WS_ORIGIN=wss://api.your-host) to point a shipped image at your real API.
# Defaults cover local dev so the app talks to a local backend out of the box.
ENV API_ORIGIN="http://localhost:8000" \
    WS_ORIGIN="ws://localhost:8000"

# Our SPA-aware config, as an envsubst template.
COPY nginx.conf /etc/nginx/templates/default.conf.template

# Copy the compiled static assets from the build stage.
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080

# Built-in health check hitting the SPA entry point on the active port.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget --quiet --tries=1 --spider "http://127.0.0.1:${PORT:-8080}/" || exit 1

# Default nginx entrypoint runs envsubst on the template first, then this CMD.
CMD ["nginx", "-g", "daemon off;"]
