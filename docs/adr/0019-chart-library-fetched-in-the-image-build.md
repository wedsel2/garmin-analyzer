# 19. The chart library is fetched in the image build, not committed

- Status: Accepted
- Date: 2026-10-04

## Context

ADR 7 chose ECharts as a vendored static file tracked by Renovate. The minified
file is 1.1 MB. The stylesheet tools (Tailwind, DaisyUI) are already fetched by
the image build at a pinned version and checksum and are not in the repository.

## Decision

- The image build fetches `echarts.min.js` from the npm package at the version
  in `ECHARTS_VERSION`, checked against a pinned SHA-256, and puts it next to
  the compiled stylesheet in `static/`.
- Renovate raises the version; the checksum is updated by hand, so the update
  is not merged automatically.
- `scripts/build-static.sh` writes both files for a local `serve`. They are
  git-ignored.
- The scripts written for this project (`static/charts.js`) are committed and
  served as they are.
- Charts must work under the existing content security policy. Tooltips are
  plain text: the policy refuses style attributes in markup, which the
  library's default tooltip content uses.

## Alternatives considered

- **Commit the file**: works without a build, but puts a megabyte of minified
  code that nobody reviews into every update's diff.
- **Load it from a CDN in the browser**: no build step, but the policy would
  have to allow another origin and every page view would tell that CDN.
- **A custom, smaller ECharts build**: needs the Node toolchain ADR 7 rules out.

## Consequences

- One way of handling third-party front-end files instead of two.
- A local `serve` shows no charts until `scripts/build-static.sh` has run; the
  pages still show the numbers.
- The build depends on the CDN being reachable; the checksum guards the content.
