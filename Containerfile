# syntax=docker/dockerfile:1

# renovate: datasource=github-releases depName=tailwindlabs/tailwindcss extractVersion=^v(?<version>.*)$
ARG TAILWIND_VERSION=4.3.3
# renovate: datasource=github-releases depName=saadeghi/daisyui extractVersion=^v(?<version>.*)$
ARG DAISYUI_VERSION=5.7.47
# renovate: datasource=npm depName=echarts
ARG ECHARTS_VERSION=6.1.0
# Set by the build to the architecture the image is for.
ARG TARGETARCH

FROM python:3.14-slim-trixie AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, so this layer is reused until the lockfile changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project

COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable


# Compiles the stylesheet with the standalone Tailwind CLI, so no Node toolchain
# is needed (ADR 7). The downloads are checked against pinned checksums: when
# Renovate raises a version, put in the new checksums by hand. Only the CLI for
# the architecture being built is fetched.
FROM python:3.14-slim-trixie AS tailwind-amd64
ARG TAILWIND_VERSION
ADD --checksum=sha256:dc61b3ac6b8c9ca874c0cc4c57b2409791a64c5540404ca5f5367360babc313a --chmod=755 \
    https://github.com/tailwindlabs/tailwindcss/releases/download/v${TAILWIND_VERSION}/tailwindcss-linux-x64 \
    /usr/local/bin/tailwindcss

FROM python:3.14-slim-trixie AS tailwind-arm64
ARG TAILWIND_VERSION
ADD --checksum=sha256:55fd0b241214eff3de1e8ee4f22796662f2d2e7a49bcfca7477cfd0bac398195 --chmod=755 \
    https://github.com/tailwindlabs/tailwindcss/releases/download/v${TAILWIND_VERSION}/tailwindcss-linux-arm64 \
    /usr/local/bin/tailwindcss

# hadolint ignore=DL3006
FROM tailwind-${TARGETARCH} AS css
ARG DAISYUI_VERSION
WORKDIR /css
ADD --checksum=sha256:85819d3fe86a852237b439b13f481481aac58e562ac47694cd11c3038e994f2a \
    https://github.com/saadeghi/daisyui/releases/download/v${DAISYUI_VERSION}/daisyui.mjs \
    styles/daisyui.mjs
COPY styles/app.css styles/app.css
COPY src/garmin_analyzer/web/templates src/garmin_analyzer/web/templates
RUN tailwindcss --input styles/app.css --output /out/app.css --minify


# The static files that are not in the repository: the stylesheet and the chart
# library, checked like the downloads above. Also what scripts/build-static.sh
# writes for local use.
FROM scratch AS static-out
ARG ECHARTS_VERSION
ADD --checksum=sha256:b66b25aeb4df84e33199dc21694014d336d222cbd9deb0e5a7c14bd6aa0d0fd0 --chmod=644 \
    https://cdn.jsdelivr.net/npm/echarts@${ECHARTS_VERSION}/dist/echarts.min.js \
    /echarts.min.js
COPY --from=css /out/app.css /app.css


FROM python:3.14-slim-trixie

# Pick up Debian security fixes newer than the base image, and drop pip: the
# runtime never installs packages and pip's vendored libraries trip the image scan.
RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/* \
    && pip uninstall -y pip \
    && groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --no-create-home app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=static-out --chown=app:app / \
    /app/.venv/lib/python3.14/site-packages/garmin_analyzer/web/static/

ARG REVISION=unknown
ENV GARMIN_ANALYZER_REVISION=${REVISION} \
    PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1

USER app

ENTRYPOINT ["garmin-analyzer"]
CMD ["healthcheck"]
