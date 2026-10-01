# 7. Custom web app: FastAPI with a server-rendered interface

- Status: Accepted
- Date: 2026-10-01

## Context

Users need to explore their metrics in a clean, modern interface in the browser
and on Android. The app also has to host account management, the Garmin link
flow and, later, goals and AI recommendations. The project should stay
Python-only so the pipeline keeps a single language toolchain.

## Decision

- Build a custom web app with **FastAPI**, serving both HTML pages and a JSON API.
- Render pages on the server with **Jinja** templates and use **HTMX** for
  partial updates.
- Style with **Tailwind CSS** and a component kit (DaisyUI), compiled by the
  standalone Tailwind binary in the image build.
- Draw charts with **ECharts**, fed by the JSON API.
- Make the site an installable **PWA** (manifest and service worker) instead of
  building a native Android app.
- No Node toolchain. HTMX and ECharts are vendored static files tracked by
  Renovate.

## Alternatives considered

- **Grafana**: fastest route to charts, but separate users, awkward per-user data
  isolation, and no place for linking accounts, goals or recommendations.
- **Single-page app (React or Vue with TypeScript)**: the richest interactivity,
  but a second language and toolchain to lint, test, scan and update.
- **Pure-Python UI frameworks (NiceGUI, Reflex, Streamlit)**: quick to start, but
  less control over look and behaviour, weak offline and install support, and
  authentication bolted on.
- **Native Android app**: a second codebase and a store release for little gain
  over an installable web app.

## Consequences

- Small amounts of JavaScript remain (chart options, the service worker); they
  live as static files without a build step.
- The JSON API must be a real, documented interface, since charts depend on it
  and a native client may later.
- The image build gains a stylesheet compilation step.
- If the interface outgrows HTMX, a single-page app can be added on the same API.
