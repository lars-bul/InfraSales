# syntax=docker/dockerfile:1
ARG PYTHON=python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170
ARG NODE=node:24-slim@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20
ARG UV=ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21

FROM ${UV} AS uv

# ── The UI ────────────────────────
# Static files, the same on every platform: built natively, not emulated, in an arm64 build.
FROM --platform=$BUILDPLATFORM ${NODE} AS ui
ENV CI=true COREPACK_ENABLE_DOWNLOAD_PROMPT=0
WORKDIR /src
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
COPY frontend/tools/api-client/package.json tools/api-client/
RUN --mount=type=cache,target=/pnpm pnpm install --frozen-lockfile --store-dir /pnpm --filter .
COPY frontend/ ./
RUN pnpm build

# ── The Python environment ──────────────────────────
FROM ${PYTHON} AS python
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project --no-editable
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-editable

# ── Runtime ──────────────────────────
FROM ${PYTHON}
ARG REVISION=unknown
LABEL org.opencontainers.image.title="InfraSales" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.licenses="LicenseRef-Proprietary"
# Security fixes Debian released.
RUN apt-get update \
 && apt-get upgrade --yes --no-install-recommends \
 && rm -rf /var/lib/apt/lists/* \
 && python -m pip uninstall --yes --no-cache-dir pip \
 && useradd --system --uid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin infrasales \
 && mkdir -p /data/sink \
 && chown 10001:10001 /data/sink
# /data/sink: the sink's mount point (SINK__URI=file:///data/sink). A fresh named volume copies
# this directory's owner, so the app's user can write Source Versions to it.
COPY --from=python /app/.venv /app/.venv
COPY --from=ui /src/dist /app/ui
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    WEB__HOST=0.0.0.0 WEB__FRONTEND_DIR=/app/ui OTEL_SERVICE_NAME=infrasales
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]
ENTRYPOINT ["infrasales"]
CMD ["web"]
