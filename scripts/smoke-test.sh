#!/usr/bin/env bash
# Smoke test: runs the image named by APP_IMAGE against a real PostgreSQL.
set -euo pipefail

export APP_IMAGE="${APP_IMAGE:-garmin-analyzer:dev}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-smoke-test}"
export COMPOSE_PROJECT_NAME="garmin-analyzer-smoke"

cleanup() { docker compose down --volumes --remove-orphans; }
trap cleanup EXIT

echo "--- image runs as non-root"
uid="$(docker run --rm --entrypoint id "$APP_IMAGE" -u)"
[ "$uid" != "0" ] || { echo "image runs as root" >&2; exit 1; }

echo "--- healthcheck passes with the database up"
docker compose run --rm app healthcheck

echo "--- healthcheck fails with the database down"
docker compose stop db
if docker compose run --rm --no-deps app healthcheck; then
    echo "healthcheck passed without a database" >&2
    exit 1
fi

echo "smoke test passed"
