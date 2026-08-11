# flare — Slack demo runbook

flare is an incident-response AI copilot. You drive it with `/flare` commands in
a Slack incident channel; a background worker investigates using an LLM (via
OpenRouter) against **synthetic telemetry scenarios**, writes structured memory
(facts, hypotheses, evidence, timeline, mitigations), posts back with
interactive buttons, and mirrors everything on a live dashboard.

## Processes

| Process | Command | Port |
|---|---|---|
| Infra (Postgres + Redis) | `make up` | 5433 / 6379 |
| API backend | `uv run --frozen python main.py` | 8000 |
| Worker (runs the LLM work) | `uv run --frozen arq flare.worker.settings.WorkerSettings` | — |
| Dashboard (optional) | `pnpm dev` (in `dashboard/`) | 3000 |

Slack must reach the backend over HTTPS → run a tunnel (cloudflared/ngrok) to :8000.

## ⚠️ Two gotchas

1. **Env var name:** use `LLM__PROVIDER__API_KEY` (double underscore). The
   `.env.example` spelling `LLM_PROVIDER__API_KEY` is wrong and fails validation.
2. **Use `uv run --frozen`** everywhere. Plain `uv run` re-resolves deps and hits
   a dependency-age policy wall; `--frozen` uses the committed lockfile.

## Part A — local stack

1. Get an OpenRouter key: https://openrouter.ai/keys (default models are free tiers).
2. `make up` then `podman ps` (wait for postgres + redis healthy). The `real`
   profile (Prometheus/Loki/Unleash) is NOT needed — tools run in `synthetic` mode.
3. `cp .env.example .env`, then set:
   ```
   DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5433/vectordb
   REDIS_URL=redis://localhost:6379/0
   APP_BASE_URL=http://localhost:8000        # becomes the tunnel URL in Part B
   LLM__PROVIDER__API_KEY=sk-or-...          # double underscore!
   TOOLS__PROVIDER=synthetic
   MITIGATION__ENABLED=true
   SLACK__SIGNING_SECRET=...                 # Part B
   SLACK__CLIENT_ID=...
   SLACK__CLIENT_SECRET=...
   SLACK__BOT_TOKEN=xoxb-...
   ```
4. `uv run --frozen alembic upgrade head`
5. Start backend + worker (two terminals):
   ```
   uv run --frozen python main.py
   uv run --frozen arq flare.worker.settings.WorkerSettings
   ```
6. Smoke: `curl -s localhost:8000/healthz` → `{"status":"ok"}`
7. Optional dashboard: `cd dashboard && pnpm install && pnpm dev`

## Part B — Slack app

1. Tunnel to 8000: `cloudflared tunnel --url http://localhost:8000` → `TUNNEL_URL`.
2. Set `APP_BASE_URL=<TUNNEL_URL>` in `.env`, restart backend.
3. api.slack.com/apps → Create New App → From a manifest. Paste the manifest
   below (replace `TUNNEL_URL`). Saving Event Subscriptions triggers the
   url_verification challenge — the `/slack/events` route answers it.
4. Copy Signing Secret, Client ID/Secret, and the Bot User OAuth Token (`xoxb-…`)
   into `.env`; restart backend + worker.
5. Install to workspace (creates the `workspaces` DB row commands need):
   ```
   https://slack.com/oauth/v2/authorize?client_id=<CLIENT_ID>&scope=commands,chat:write,channels:history,channels:read&redirect_uri=https://TUNNEL_URL/slack/oauth/callback
   ```
   Approve → JSON `{"ok": true, ...}`.

   Fallback (skip OAuth) — insert the workspace row manually:
   ```
   podman exec -it flare-postgres psql -U postgres -d vectordb -c \
     "INSERT INTO workspaces (id, slack_team_id, name, created_at, updated_at) \
      VALUES (gen_random_uuid(), 'T0123456789', 'Demo', now(), now());"
   ```

### Slack app manifest

```yaml
display_information:
  name: flare
features:
  bot_user:
    display_name: flare
    always_online: true
  slash_commands:
    - command: /flare
      url: https://TUNNEL_URL/slack/commands
      description: Incident copilot
      usage_hint: 'start "title" --sev sev2'
oauth_config:
  redirect_urls:
    - https://TUNNEL_URL/slack/oauth/callback
  scopes:
    bot:
      - commands
      - chat:write
      - channels:history
      - channels:read
settings:
  event_subscriptions:
    request_url: https://TUNNEL_URL/slack/events
    bot_events:
      - message.channels
      - member_joined_channel
  interactivity:
    is_enabled: true
    request_url: https://TUNNEL_URL/slack/interactions
```

## Part C — demo script (in Slack)

1. Create `#inc-checkout`, then `/invite @flare`.
2. `/flare start "Checkout latency spike" --sev sev2 --desc p99 climbing on checkout-api`
   → bot posts the incident card; worker investigates the synthetic
   `db_latency_spike` scenario and posts findings.
3. Type context in-channel (becomes facts/timeline, can trigger re-investigation):
   - `We deployed checkout-api v423 at 14:05`
   - `Error rate started climbing right after`
4. Reads: `/flare hypotheses`, `/flare evidence`, `/flare timeline`, `/flare brief`
5. `/flare mitigation` → proposes ranked options with Approve/Reject buttons
   (human-in-the-loop; nothing mutating happens without a click).
6. Confirm/reject a hypothesis via its buttons (drives ranking).
7. `/flare draft-update status` → opens an editable comms modal (audiences:
   internal | support | status | exec).
8. `/flare mode active` (proactive refresh + recovery watch), `/flare postmortem`.
9. Dashboard: open http://localhost:3000 for the live incident view.

### Command reference
`start`, `investigate <what>`, `validate <claim>`, `correct "..."`,
`mode <quiet|scribe|assist|active>`, `mitigation`, `draft-update <audience>`,
`postmortem`, `refresh`, and reads
`hypotheses|evidence|questions|decisions|timeline|brief|dashboard`.
