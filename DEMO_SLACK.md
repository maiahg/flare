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
2. Bring up a **clean** Postgres + Redis (the `-v` wipes any stale volume from
   earlier work so the schema matches the current migrations):
   ```
   podman compose down -v && make up
   podman ps            # wait for flare-postgres + flare-redis healthy
   podman port flare-postgres   # confirm 5432/tcp -> 0.0.0.0:5433
   ```
   The `real` profile (Prometheus/Loki/Unleash) is NOT needed — synthetic mode.
   If you skip the reset and the **worker later crashes with**
   `column "provider_request_id" ... does not exist`, your volume is stale:
   `podman compose down -v && make up` then re-run migrations (step 4).
3. `cp .env.example .env`, then set:
   ```
   DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5433/vectordb
   REDIS_URL=redis://localhost:6379/0
   APP_BASE_URL=http://localhost:8000        # becomes the tunnel URL in Part B
   DASHBOARD_BASE_URL=http://localhost:3000  # dashboard links stay on :3000
   LLM__PROVIDER__API_KEY=sk-or-...          # double underscore!
   TOOLS__PROVIDER=synthetic
   MITIGATION__ENABLED=true
   RECOVERY__SCENARIO=orders_backlog_recovered  # post-mitigation telemetry
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

## Reset between demos

To start each demo from a clean slate (no incidents, hypotheses, evidence, runs,
etc.) **without** having to re-install the Slack app, wipe just the incident data
and flush Redis:

```
# Wipes every incident-scoped table (cascades from `incidents`); KEEPS the
# `workspaces` + `users` rows, so the Slack install / OAuth still works.
podman exec flare-postgres psql -U postgres -d vectordb -c "TRUNCATE incidents CASCADE;"

# Clears ephemeral state: Slack event-dedupe keys, recovery tokens, rate-limiter
# counters, the arq job queue, and any open SSE bookkeeping.
podman exec flare-redis redis-cli FLUSHALL
```

Then reload the dashboard — the incident list is empty and you can `/flare start`
a fresh one. Restarting the backend/worker is not required.

> **Nuclear option** (also resets migrations and *removes* the workspace install,
> so you must re-run step 4 + re-OAuth in Part B):
> `podman compose down -v && make up && uv run --frozen alembic upgrade head`

## Part C — demo script (in Slack)

The worker investigates the synthetic **`orders_backlog`** scenario: an
orders-worker queue backing up after deploy **#7788** (a redis-rb 5.0 upgrade
that quietly shrank the connection pool 25→5). It ships with **two decoys** the
team will argue over — a co-timed feature-flag ramp (`async_order_confirmation`,
reinforced by a real past incident) and a cosmetic web-storefront deploy — while
the evidence (pool-exhaustion logs, blame on `redis.rb`, a healthy
payments-gateway) points squarely at #7788.

**Cast** — invite these people (or use a few test accounts and post as each):

| Handle | Role |
|---|---|
| `@priya` | Incident Commander — runs every `/flare` command |
| `@sam` | SRE watching the dashboards |
| `@omar` | orders-team — shipped deploy #7788 |
| `@rey` | product — owns the `async_order_confirmation` flag |
| `@lin` | payments on-call |

**Setup:** create `#inc-orders-backlog`, then `/invite @flare`.

**Beat 1 — Declare the incident**
```
priya:  /flare start "Orders stuck in pending — checkout success dropping" --sev sev1 --desc order confirmations backing up since ~02:16 UTC
```
→ bot posts the incident card and **silently** starts a read-only investigation.
By default an incident is in **quiet** mode: the agent investigates and writes to
memory/dashboard but does not post findings or mitigations to the channel unless
you ask (a read command, `/flare investigate|validate`, or `/flare mode assist`
to turn on proactive posting). Nothing happens without a command — inviting the
bot to a channel no longer opens an incident on its own.

**Beat 2 — The team piles in with context** (each line becomes cited memory —
facts, decisions, action items — and can trigger a re-investigation; only
consequential events like deploys and mitigations land on the timeline, not
every message):
```
sam:   Order success on the checkout dashboard fell 99.3% → 71% starting 02:16. Customers see a "pending" spinner.
rey:   Heads up — I ramped async_order_confirmation 0 → 100 at 02:15. Could be us. Want me to roll it back?
omar:  I also shipped #7788 to orders-worker at 02:14 — a redis-rb 5.0 upgrade. Timing lines up too.
lin:   payments-gateway had a p99 blip at 01:58 but it was normal again by 02:02. I don't think payments is involved.
```

**Beat 3 — Ask the bot what it found** (in quiet mode this is how findings
surface — the reads are ephemeral, the dashboard has the full picture):
```
priya:  /flare hypotheses
priya:  /flare evidence
priya:  /flare timeline
```

> **Private vs public:** `/flare <action>` answers you *privately* (ephemeral —
> only you see it). To broadcast an answer so the whole channel sees it, mention
> the bot instead: `@flare hypotheses`, `@flare validate "…"`, `@flare status
> resolved`. `@flare` supports reads, `investigate`/`validate`, and `status`;
> everything else (start, mode, correct, mitigation, draft-update, postmortem)
> stays on `/flare` — some open a dialog, which a mention can't do.
→ leading hypothesis: **deploy #7788 shrank the orders-worker Redis connection
pool 25→5**; evidence is the pool-exhaustion logs + blame on `redis.rb`;
payments is healthy; the flag ramp and CSS deploy are noted but not causal.

**Beat 4 — Debate the decoys** (the interesting part):
```
rey:    So it's NOT the flag ramp? We had that duplicate-email incident last August.
priya:  /flare validate "the async_order_confirmation flag ramp caused the incident"
```
→ bot pushes back: the errors are Redis pool timeouts in orders-worker, nothing
the flag toggles.
```
sam:    Confirmed — orders-worker is logging "connection pool exhausted: 5/5 in use, 8k jobs queued". Queue depth 8,200 and climbing.
omar:   That's the redis-rb 5 default. My PR dropped the pool 25 → 5 without me noticing. It's #7788.
```

**Beat 5 — Correct the record** (someone blamed payments early):
```
priya:  /flare correct "payments-gateway is healthy; root cause is the orders-worker Redis connection-pool shrink in deploy #7788"
```
→ Scribe reconciles memory: rejects the payments angle, strengthens #7788.

**Beat 6 — Mitigation (human-in-the-loop)**
```
priya:  /flare mitigation
```
→ bot proposes ranked, reversible options (e.g. roll back #7788 / restore
`ConnectionPool` size to 25). **Click Approve** on the top one — nothing is
applied automatically; approval records intent only.
```
priya:  Decision: we're rolling back #7788 and pinning the orders-worker Redis pool back to 25 as the fix.
omar:   Rolling back #7788 and pinning pool size back to 25.
```
→ Scribe records both as **decisions** on the incident (the rollback also lands
on the timeline as a mitigation). Read them back with `/flare decisions`.

**Beat 6b — Capture follow-ups** (each becomes a postmortem action item):
```
sam:    Action item: add a pool-size regression test so a redis-rb bump can't silently shrink the pool again.
priya:  Follow-up: we should alert on orders-worker queue depth > 1000 so we catch this earlier next time.
rey:    To-do: document the async_order_confirmation ramp coincidence in the runbook so we don't chase that decoy again.
```
→ Scribe records these as **action items** — they surface in the postmortem's
follow-ups section and on the dashboard. (Decisions and action items are also
extracted by the LLM scribe from natural phrasing; the `decision:` / `action
item:` / `follow-up:` prefixes above just make them deterministic for the demo.)

**Beat 7 — Confirm the hypothesis**
Click **Confirm** on the #7788 hypothesis card (drives ranking and locks the
postmortem's root cause to a human-confirmed claim).

**Beat 8 — Comms draft**
```
priya:  /flare draft-update status
```
→ editable modal; pick the **status** audience (external-safe: never shows
unconfirmed hypotheses). Edit and submit.

**Beat 9 — Recovery + lifecycle**
Approving a mitigation (Beat 6/7) schedules a read-only **recovery watch**. With
`RECOVERY__SCENARIO=orders_backlog_recovered` set, that poll reads the
post-mitigation telemetry (p99 drained back to baseline), so the watcher observes
recovery on its own: it flips the incident to `monitoring` and records a
metrics-sourced **`Recovery observed: …`** entry on the timeline (a real event
from a tool call, not something anyone typed). If you leave `RECOVERY__SCENARIO`
unset the investigation scenario stays elevated and you narrate recovery by hand.
```
sam:    Queue is draining — success back to 98% at 02:41, orders-worker throughput recovering.
priya:  /flare status monitoring
priya:  /flare status resolved
```
> The timeline is a log of **consequential events**, not a chat transcript: the
> only entries are deploys (e.g. `omar` shipping / rolling back #7788),
> mitigations, and the recovery observation above. Read it with `/flare
> timeline`; it also renders in the postmortem's Timeline section.

**Beat 10 — Postmortem**
```
priya:  /flare postmortem
```
→ drafted from memory; every claim cited; root cause = the human-confirmed #7788
pool shrink. The **Decisions** section carries the rollback/pool-pin decisions
from Beat 6 and the **Action items** section carries the three follow-ups from
Beat 6b. Optional: `/flare mode active` earlier to show proactive refresh.

**Dashboard:** keep http://localhost:3000 open on the incident throughout —
overview, runs, evidence, hypotheses and the postmortem all update live. (The
standalone Timeline tab was removed; the timeline of consequential events now
lives in the postmortem's Timeline section.)

### Command reference
`start`, `investigate <what>`, `validate <claim>`, `correct "..."`,
`mode <quiet|scribe|assist|active>`, `status <open|mitigating|monitoring|resolved|closed>`,
`mitigation`, `draft-update <audience>`,
`postmortem`, `refresh`, and reads
`hypotheses|evidence|questions|decisions|timeline|brief|dashboard`.
