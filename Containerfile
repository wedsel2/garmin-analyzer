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

ARG REVISION=unknown
ENV GARMIN_ANALYZER_REVISION=${REVISION} \
    PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1

USER app

ENTRYPOINT ["garmin-analyzer"]
CMD ["healthcheck"]
