#!/usr/bin/env bash
# Compiles the stylesheet and fetches the chart library and HTMX the way the
# image build does, and puts them where a local `garmin-analyzer serve` finds them. Needs
# Docker; the results are git-ignored.
set -euo pipefail

cd "$(dirname "$0")/.."
docker build --file Containerfile --target static-out \
    --output type=local,dest=src/garmin_analyzer/web/static .
echo "wrote app.css, echarts.min.js and htmx.min.js to src/garmin_analyzer/web/static"
