# flare

An incident-response AI copilot. Drive it by mentioning `@flare` in a Slack
incident channel; a background worker investigates using an LLM (via OpenRouter)
against telemetry (synthetic scenarios by default, or real Prometheus/Loki/
GitHub/Unleash backends), writes structured incident memory (facts, hypotheses,
evidence, timeline, mitigations), posts back with interactive human-in-the-loop
buttons, and mirrors everything on a live Next.js dashboard.

## Quick start

Prereqs: `uv`, `podman`, and (for the dashboard) `pnpm` + `node`.

```bash
make up                                              # Postgres + Redis
cp .env.example .env                                 # then set LLM__PROVIDER__API_KEY
uv run --frozen alembic upgrade head                 # migrations
uv run --frozen python main.py                       # API on :8000
uv run --frozen arq flare.worker.settings.WorkerSettings  # worker (separate terminal)
cd dashboard && pnpm install && pnpm dev             # dashboard on :3000 (optional)
```

Notes:
- Use `uv run --frozen` (plain `uv run` may re-resolve and fail on dependency-age policy).
- The env var is `LLM__PROVIDER__API_KEY` (double underscore). Get a key at
  https://openrouter.ai/keys.

## Full Slack demo

See **[DEMO_SLACK.md](./DEMO_SLACK.md)** for the end-to-end walkthrough: tunneling
to Slack, the Slack app manifest (scopes, events, mentions, interactivity,
OAuth), installing to a workspace, and a step-by-step `@flare` demo script.
