#!/usr/bin/env bash
# Compiles the stylesheet the way the image build does and puts it where a
# local `garmin-analyzer serve` finds it. Needs Docker; the result is git-ignored.
set -euo pipefail

cd "$(dirname "$0")/.."
docker build --file Containerfile --target css-out \
    --output type=local,dest=src/garmin_analyzer/web/static .
echo "wrote src/garmin_analyzer/web/static/app.css"
