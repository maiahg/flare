# flare dashboard

Read-only Next.js + TanStack Query dashboard for the flare incident copilot
(PR 1.5, milestone M1). It renders memory from the FastAPI backend and updates
live over SSE.

## Develop

```bash
pnpm install
# regenerate the typed client whenever the backend read API changes:
#   (from repo root) uv run python scripts/dump_openapi.py
pnpm gen:api
pnpm dev            # http://localhost:3000, proxies /api/* to :8000
```

Set `FLARE_API_URL` to point at a non-default backend.

## Test

```bash
pnpm typecheck      # tsc --noEmit
pnpm test           # Vitest + Testing Library component tests
pnpm build          # production build

# E2E (needs the full stack up: make up && make run on the backend):
pnpm exec playwright install chromium   # once
pnpm test:e2e
```

The Playwright spec (`e2e/live-update.spec.ts`) proves the M1 exit criterion —
manually-inserted memory renders live without a reload. It skips itself until
the write/seed API lands (PR 5.1).

## Typed API client

`src/lib/api-types.ts` is generated from the backend's `openapi.json`; never
edit it by hand. `src/lib/api.ts` wraps it with `openapi-fetch` so every call
is checked against the backend contract at compile time.
