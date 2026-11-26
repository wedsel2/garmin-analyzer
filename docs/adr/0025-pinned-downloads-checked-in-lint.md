# 25. Pinned downloads in the Containerfile are checked against their checksums in lint

- Status: Accepted
- Date: 2026-11-26

## Context

The Containerfile fetches the Tailwind CLI, daisyUI, ECharts and HTMX with
`ADD --checksum=sha256:...`, the version coming from a global `ARG *_VERSION`
that Renovate raises ([ADR 19](0019-chart-library-fetched-in-the-image-build.md),
[ADR 23](0023-renovate-runs-all-monday-and-tracks-tool-versions.md)). Renovate
cannot update the checksums, so they are changed by hand and these updates are
not merged automatically.

The Tailwind 4.3.3 → 4.3.5 update was merged with the 4.3.3 checksums. CI stayed
green for two weeks: BuildKit keys an `ADD --checksum` layer on the checksum, so
the image job's GitHub Actions cache kept serving the 4.3.3 download, and the
released image shipped Tailwind 4.3.3 while claiming 4.3.5. It failed only once
the cache entry was evicted. The image job also builds amd64 only, so it never
checks the arm64 checksum at all.

## Decision

`scripts/check_pinned_downloads.py` runs as the `pinned-downloads` pre-commit
hook, so the lint job runs it on every pull request and push. It:

- expands each remote `ADD` URL from the global `ARG` defaults, for every
  architecture stage, not only the one being built;
- downloads each file with no cache and compares its sha256 with `--checksum`;
- fails on a mismatch, a failed download, a malformed checksum, a remote `ADD`
  without `--checksum`, or a variable that has no global default.

It uses the standard library only (no Node toolchain, ADR 7). Locally the hook
runs only when the Containerfile or the script changes. Tests cover the parser
and the comparison with a local fetcher; they never download.

## Alternatives considered

- **Build the static stages without cache** (`no-cache-filters` for
  `tailwind-*`, `css`, `static-out` in the image job): uses BuildKit's own
  verification and needs no new code, but checks only the architecture CI builds
  (amd64), fails only after lint and tests, and recompiles the stylesheet on
  every run.
- **Renovate `postUpgradeTasks` to rewrite the checksums**: not available on the
  hosted Renovate app.
- **Read digests from the GitHub release API instead of downloading**: avoids
  about 220 MB of Tailwind binaries per run, but jsdelivr offers no such API, so
  two mechanisms would be needed for four files.

## Consequences

- A version bump without new checksums fails `lint` on the Renovate pull
  request, and the message gives the sha256 to paste in.
- The lint job needs network to GitHub release downloads and jsdelivr, and
  downloads about 230 MB per run. An outage at either host fails lint; rerun
  the job.
- The image job keeps its cache. A cached `ADD` layer can no longer hide a stale
  checksum, because lint has already downloaded the file for that checksum.
