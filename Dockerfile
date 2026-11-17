FROM oven/bun:1.3.14 AS frontend
WORKDIR /web
COPY frontend/package.json frontend/bun.lock ./
RUN bun install --frozen-lockfile
COPY frontend/index.html frontend/tsconfig.json frontend/vite.config.ts ./
COPY frontend/src ./src
COPY frontend/public ./public
ARG VITE_AUTH_PROVIDER=local
ARG VITE_GOOGLE_API_KEY
ARG VITE_GOOGLE_AUTH_DOMAIN
ARG VITE_GOOGLE_PROJECT_ID
ARG VITE_GOOGLE_APP_ID
ENV VITE_AUTH_PROVIDER=$VITE_AUTH_PROVIDER VITE_GOOGLE_API_KEY=$VITE_GOOGLE_API_KEY VITE_GOOGLE_AUTH_DOMAIN=$VITE_GOOGLE_AUTH_DOMAIN VITE_GOOGLE_PROJECT_ID=$VITE_GOOGLE_PROJECT_ID VITE_GOOGLE_APP_ID=$VITE_GOOGLE_APP_ID
RUN bun run build

FROM python:3.13-slim
WORKDIR /app
COPY backend ./backend
ARG BACKEND_EXTRAS=google,agent
# Match the checked-in lockfile instead of resolving new versions at deployment.
RUN pip install --no-cache-dir uv==0.6.5
WORKDIR /app/backend
RUN set -eu; extras=""; for extra in $(echo "$BACKEND_EXTRAS" | tr ',' ' '); do extras="$extras --extra $extra"; done; \
    uv sync --frozen --no-dev --no-editable $extras && \
    useradd --uid 10001 --create-home appuser
ENV PATH="/app/backend/.venv/bin:$PATH"
WORKDIR /app
COPY --from=frontend /web/dist /app/static
ENV PORT=8080 APP_STATIC_DIR=/app/static APP_ENV=production COOKIE_SECURE=true
USER appuser
EXPOSE 8080
CMD ["python", "-m", "app_core.serve"]
