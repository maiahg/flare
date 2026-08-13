# flare dashboard

Read-only Next.js + TanStack Query dashboard for the flare incident copilot
(PR 1.5, milestone M1). It renders memory from the FastAPI backend and updates
live over SSE.

## Develop

```bash
npm install
# regenerate the typed client whenever the backend read API changes:
#   (from repo root) uv run python scripts/dump_openapi.py
npm run gen:api
npm run dev         # http://localhost:3000, proxies /api/* to :8000
```

Set `FLARE_API_URL` to point at a non-default backend.

## Test

```bash
npm run typecheck   # tsc --noEmit
npm test            # Vitest + Testing Library component tests
npm run build       # production build

# E2E (needs the full stack up: make up && make run on the backend):
npm exec playwright install chromium    # once
npm run test:e2e
```

The Playwright spec (`e2e/live-update.spec.ts`) proves the M1 exit criterion —
manually-inserted memory renders live without a reload. It skips itself until
the write/seed API lands (PR 5.1).

## Typed API client

`src/lib/api-types.ts` is generated from the backend's `openapi.json`; never
edit it by hand. `src/lib/api.ts` wraps it with `openapi-fetch` so every call
is checked against the backend contract at compile time.
