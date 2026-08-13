# Running Flare

This guide walks through running Flare locally.
---

## 1. Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.13+ | pinned in `.python-version`; the project targets `>=3.13` |
| [uv](https://docs.astral.sh/uv/) | recent | dependency + venv manager |
| Podman (or Docker) + Compose | recent | `Makefile` uses `podman compose`; override with `COMPOSE=docker compose` |
| Node + npm | Node 20+, npm 10+ | only for the dashboard |
| A public tunnel | — | ngrok / Cloudflare Tunnel — Slack must reach your local web tier |


---

## 2. Install dependencies

```bash
cd /path/to/flare

# Python deps into a local .venv
uv sync

# Dashboard deps (separate app)
cd dashboard && npm install && cd ..
```

---

## 3. Configure environment

Copy the example env and fill in real values:

```bash
cp .env.example .env
```

Key variables (`flare/config.py` reads these; nested settings use `__`):

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:password@localhost:5433/vectordb` (matches `compose.yml`) |
| `REDIS_URL` | `redis://localhost:6379/0` |
| `APP_BASE_URL` | Public URL of the web tier (your tunnel URL in Slack mode) |
| `DASHBOARD_BASE_URL` | `http://localhost:3000` - used in the links Flare posts to Slack |
| `SLACK__SIGNING_SECRET` | From your Slack app - verifies inbound requests |
| `SLACK__CLIENT_ID` / `SLACK__CLIENT_SECRET` | OAuth install flow |
| `SLACK__BOT_TOKEN` | `xoxb-…` bot token used to post |
| `LLM__PROVIDER__API_KEY` | OpenRouter API key |
| `TOOLS__PROVIDER` | `synthetic` (fixtures) or `real` (talk to Prometheus/Loki/GitHub/Unleash) |
| `TOOLS__DEFAULT_SERVICE` | Service an incident defaults to when its trigger names none |
| `MITIGATION__ENABLED` / `MITIGATION__MAX_OPTIONS` | Whether/how many mitigation options a run proposes |
| `RECOVERY__SCENARIO` | Post-mitigation fixture the recovery watch reads (synthetic only) |

The `real`-profile backends (`TOOLS__PROMETHEUS__BASE_URL`, `…LOKI…`,
`…GITHUB…`, `…UNLEASH…`) only matter when `TOOLS__PROVIDER=real`.

---

## 4. Start infrastructure (Postgres + Redis)

```bash
make up            # podman compose up -d
```

This starts Postgres (pgvector) on `localhost:5433` and Redis on
`localhost:6379`. To also start the real observability stack (Prometheus, Loki,
Unleash) use the `real` compose profile:

```bash
podman compose --profile real up -d
```

Tear everything down with `make down`.

---

## 5. Apply database migrations

Alembic reads `DATABASE_URL` via `flare/config.py`, so no URL is hardcoded in
`alembic.ini`.

```bash
uv run alembic upgrade head
# or, if uv can't resolve deps:
./.venv/bin/alembic upgrade head
```

You should see migrations `0001`–`0005` apply (core tables, revision sequence,
data-erasure tombstones, incident channel name).

---

## 6. Run the backend processes

Flare needs two backend processes running side by side.

**Terminal A — web tier (FastAPI):**

```bash
make run
# = uv run python main.py
# or: ./.venv/bin/python main.py
```

**Terminal B — worker (arq):**

```bash
make worker
# = uv run arq flare.worker.settings.WorkerSettings
# or: ./.venv/bin/arq flare.worker.settings.WorkerSettings
```

Quick health check:

```bash
curl -s http://127.0.0.1:8000/health
```

---

## 7. Run the dashboard (optional but recommended)

```bash
cd dashboard
npm run gen:api     # regenerate the typed client from ../openapi.json (only if the API changed)
npm run dev         # http://localhost:3000, proxies /api/* to :8000
```

Point at a non-default backend with `FLARE_API_URL`. The dashboard is
**read-only**, it renders incident memory, runs, tool calls, tokens, and the
postmortem draft, and updates live over SSE.

---

## 8. Connect Slack

Flare's only command surface is `@flare` mentions in a channel.

1. Start a tunnel to the web tier and note the public URL:
   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```
2. Create the Slack app from `slack-manifest.yml`, replacing `TUNNEL_URL`
   with your tunnel host. It configures:
   - Event subscriptions → `https://TUNNEL_URL/slack/events`
     (`message.channels`, `app_mention`, `member_joined_channel`)
   - Interactivity → `https://TUNNEL_URL/slack/interactions`
   - OAuth redirect → `https://TUNNEL_URL/slack/oauth/callback`
   - Bot scopes: `chat:write`, `channels:history`, `channels:read`,
     `app_mentions:read`
3. Set `.env`: `APP_BASE_URL=https://TUNNEL_URL`, plus the signing secret,
   client id/secret, and bot token from the app's settings.
4. Install the app to your workspace (visit
   `https://TUNNEL_URL/slack/oauth/callback` completes the OAuth flow and writes
   a `workspaces` row), then invite `@flare` into a channel.

Restart the web tier after changing `.env`.

---

## 9. Drive an incident

Everything is driven by `@flare` mentions in the channel:

```text
@flare start "Checkout p99 spiking" --sev sev2 --desc "orders backlog climbing"
@flare investigate what changed in checkout-api in the last hour
@flare validate the checkout-api deploy caused the p99 spike
@flare status mitigating          # open | mitigating | monitoring | resolved | closed
@flare mitigation                 # propose options (approval-gated; nothing is applied)
@flare correct "the deploy was 14:02 not 13:40"
@flare postmortem
@flare help
```

What happens under the hood:

- Ordinary channel messages are scribed → signals → grounded claims; triage
  decides whether to trigger an investigation run (novelty + score), coalescing
  bursts into one run.
- Investigation runs fan out the read agents through the ToolBroker (all
  reads audited, read-only), reason (hypothesis ⇄ critic), commit cited memory,
  and post findings to the channel.
- `@flare mitigation` proposes options behind an approval card; approving is
  recorded as human intent — Flare never applies a mitigation itself.
- Watch the whole trace live on the dashboard at
  `http://localhost:3000`.

---

## 10. Commands

`@flare` mentions in a channel are the only command surface. Every reply
posts publicly. The first word after
`@flare` is the command; anything unrecognised (or `@flare help`) prints usage.

### Lifecycle

| Command | What it does |
|---|---|
| `@flare start "<title>" [--sev sevN] [--desc <text>]` | Open/adopt an incident on this channel. `--sev` ∈ `sev1..sev4`, `unknown` (default `unknown`); `--desc` is optional. Posts the incident card + dashboard link. |
| `@flare status <status>` | Move the incident status. `<status>` ∈ `open`, `mitigating`, `monitoring`, `resolved`, `closed`. `resolved`/`closed` stop the active loop, recovery watch, and scribing. |
| `@flare mode <mode>` | Set how proactively Flare posts. `<mode>` ∈ `quiet` (default — no proactive posts), `scribe`, `assist`, `active`. |

### Investigation

| Command | What it does |
|---|---|
| `@flare investigate <what>` | Force an investigation run focused on `<what>`, bypassing the mode + governor floor. Enqueues an adaptive run on the worker. |
| `@flare validate <claim>` | Verify one claim against fresh evidence. Fuzzy-matches an existing fact/hypothesis (else treats it as ad-hoc) and returns a verdict: supported / contradicted / inconclusive. Must cite evidence or downgrades to inconclusive. |
| `@flare mitigation` | Propose mitigation options behind an **Approve/Reject** card. Approving records human intent. Gated by `MITIGATION__ENABLED` / `MITIGATION__MAX_OPTIONS`. |
| `@flare correct "<what is actually true>"` | Record a human correction; reconciles memory against it on the worker (`reconcile_correction`). Human statements outrank inferences and are never overridden. |
| `@flare postmortem` | Generate/update the postmortem draft from memory (every claim links to its evidence). Appears on the dashboard. |

### Reads (rendered from committed memory)

| Command | What it shows |
|---|---|
| `@flare hypotheses` | Current hypotheses with supporting/contradicting evidence. |
| `@flare evidence [--system <name>]` | Committed evidence; optionally filter to one source system. |
| `@flare questions` | Open questions. |
| `@flare decisions` | Decisions recorded so far. |
| `@flare timeline` | Latest 10 consequential timeline entries (deploys, mitigations, observed recovery). |
| `@flare brief` | A condensed situation brief. |
| `@flare dashboard` | Link to the incident's dashboard page. |
| `@flare help` | Print the usage string (also shown for any unknown command). |

> Reads, `investigate`, `validate`, `status`, `mode`, `correct`, and
> `postmortem` all require an incident already tracking the channel — run
> `@flare start` first, or Flare replies that no incident is tracking the
> channel.

### Make targets (local dev)

| Target | Command |
|---|---|
| `make up` / `make down` | Start / stop the compose infra (Postgres + Redis) |
| `make run` | Web tier — `uv run python main.py` (uvicorn on `:8000`) |
| `make worker` | arq worker — `uv run arq flare.worker.settings.WorkerSettings` |
| `make lint` | `ruff check .` (do **not** run `ruff format`) |
| `make fmt` | `ruff format` + `ruff check --fix` (avoid — rewrites unrelated lines) |
| `make typecheck` | `mypy .` |
