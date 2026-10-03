# syntax=docker/dockerfile:1
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
# is needed (ADR 7). Both downloads are checked against a pinned checksum: when
# Renovate raises a version, put in the new checksums by hand. The CLI is the
# x64 build, as the released image is.
FROM python:3.14-slim-trixie AS css

# renovate: datasource=github-releases depName=tailwindlabs/tailwindcss extractVersion=^v(?<version>.*)$
ARG TAILWIND_VERSION=4.3.3
# renovate: datasource=github-releases depName=saadeghi/daisyui extractVersion=^v(?<version>.*)$
ARG DAISYUI_VERSION=5.7.47

WORKDIR /css
ADD --checksum=sha256:dc61b3ac6b8c9ca874c0cc4c57b2409791a64c5540404ca5f5367360babc313a --chmod=755 \
    https://github.com/tailwindlabs/tailwindcss/releases/download/v${TAILWIND_VERSION}/tailwindcss-linux-x64 \
    /usr/local/bin/tailwindcss
ADD --checksum=sha256:85819d3fe86a852237b439b13f481481aac58e562ac47694cd11c3038e994f2a \
    https://github.com/saadeghi/daisyui/releases/download/v${DAISYUI_VERSION}/daisyui.mjs \
    styles/daisyui.mjs
COPY styles/app.css styles/app.css
COPY src/garmin_analyzer/web/templates src/garmin_analyzer/web/templates
RUN tailwindcss --input styles/app.css --output /out/app.css --minify


# Only the stylesheet, for scripts/build-css.sh.
FROM scratch AS css-out
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
COPY --from=css --chown=app:app /out/app.css \
    /app/.venv/lib/python3.14/site-packages/garmin_analyzer/web/static/app.css

ARG REVISION=unknown
ENV GARMIN_ANALYZER_REVISION=${REVISION} \
    PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1

USER app

ENTRYPOINT ["garmin-analyzer"]
CMD ["healthcheck"]
