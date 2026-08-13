# Flare

Flare is an AI incident copilot that lives in a Slack channel. Flare is invoked with `@flare` mentions in an incident channel

It reads an incident's channel messages and real telemetry, investigates, keeps a grounded and cited memory of what is known, proposes mitigations, and drafts a postmortem all under human authority.


## Tech stack

| Layer | Technology |
|---|---|
| Web tier | FastAPI (fast Slack ACKs + versioned `/api/v1` REST) |
| Worker | arq (Redis-backed queue — runs all LLM + backend work) |
| Orchestration | LangGraph state machine (agent fan-out, human-in-the-loop interrupts, per-node supersede) |
| Storage | Postgres + pgvector (grounded memory, claims, audit trail) |
| Queue / cache | Redis (job queue, tool cache, run coordination) |
| LLM | Provider-agnostic OpenAI-compatible client (OpenRouter by default) |
| Dashboard | Next.js (read-only UI over `/api/v1`, live via SSE) |
| Migrations | Alembic |
| Tooling | uv, ruff, mypy |

## Demo

Dashboard overview:

<img width="1910" height="1070" alt="image" src="https://github.com/user-attachments/assets/6dc8d2a0-96e2-4567-96e6-84b4a2cf3e5c" />

Walkthroughs:

https://github.com/user-attachments/assets/f3cda2a3-02ee-4491-9b7e-77f58e90bda6

https://github.com/user-attachments/assets/ddaaddce-5c79-4aba-ad1f-e78e9fbc5f80

https://github.com/user-attachments/assets/28691b6b-9461-446a-b391-29538a2d222f

<img width="1905" height="1071" alt="image" src="https://github.com/user-attachments/assets/6372eb49-88fa-4ac9-a319-7e9f40d0618b" />

## Documentation

- [docs/DESIGN.md](docs/DESIGN.md) — architecture, data model, runtime flow,
  the investigation graph, safety model, and key design decisions & trade-offs.
- [docs/RUNNING.md](docs/RUNNING.md)— running Flare locally end-to-end:
  prerequisites, config, infra, migrations, the web/worker/dashboard processes,
  connecting Slack, driving an incident, and the full `@flare` command reference.
