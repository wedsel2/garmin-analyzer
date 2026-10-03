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

# Expect the healthcheck to fail with a specific message, so an unrelated
# failure (such as an image that could not be pulled) does not count as a pass.
expect_unhealthy() {
    local expected="$1" output
    shift
    if output="$(docker compose run --rm "$@" web healthcheck 2>&1)"; then
        echo "healthcheck passed unexpectedly" >&2
        exit 1
    fi
    if ! grep -q "$expected" <<<"$output"; then
        echo "healthcheck failed for another reason than '$expected':" >&2
        echo "$output" >&2
        exit 1
    fi
}

echo "--- database starts"
# Registry pulls fail now and then on CI runners; retry before giving up.
for attempt in 1 2 3; do
    if docker compose up --detach --wait db; then
        break
    fi
    [ "$attempt" -lt 3 ] || { echo "database did not start" >&2; exit 1; }
    sleep 15
done

echo "--- healthcheck fails before migrations are applied"
expect_unhealthy "database schema is not up to date"

echo "--- migrations apply from the packaged image"
docker compose run --rm web migrate

echo "--- healthcheck passes on the migrated database"
docker compose run --rm web healthcheck

echo "--- a user can be created"
docker compose run --rm web user-add smoke@example.com

echo "--- web interface starts and serves the sign-in page and its stylesheet"
docker compose up --detach --wait web
docker compose exec -T web python -c '
import urllib.request as r
assert b"Sign in" in r.urlopen("http://127.0.0.1:8000/login", timeout=5).read()
r.urlopen("http://127.0.0.1:8000/static/app.css", timeout=5)
'

echo "--- healthcheck fails with the database down"
docker compose stop db
expect_unhealthy "database error" --no-deps

echo "smoke test passed"
