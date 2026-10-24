# ChronoTwin

**Team Spookies · ChronoForge 2026 · NITK Surathkal · Track: Agentic AI · Theme: Cities of the Future**

A living 3D digital twin run by cooperating AI agents. They **detect** a cascading city
failure, **negotiate** a joint plan using real tool calls, **verify** it in simulation, and
only then ask a human to **approve** and **act**.

> Python 3.11+ · FastAPI · NetworkX · custom discrete-time simulator · Redpanda/Kafka ·
> Redis · PostgreSQL + TimescaleDB · WebSockets · React + Three.js

## Design principles

1. **LLM calls scale with incidents, not data.** Raw sensor data is reduced by code before any agent sees it.
2. **Proposals are data, not actions.** Agents only call read/estimate tools while planning; mutating
   actions are returned as `Action` objects and executed only after verification + approval.
3. **Verify before act.** Nothing reaches the twin unless the Critic's simulation passes.
4. **Humans approve high-impact actions.** `HIGH` impact waits for operator approval.
5. **Untrusted input is never a command.** Only structured fields reach agents; free text is stored, never prompted.
6. **Runs offline.** `LLM_MODE=scripted` or `ollama` needs no live API.

## Prerequisites

| Tool | Version | Needed for |
|---|---|---|
| Python | 3.11+ | backend (always) |
| Node.js | 18+ (npm 9+) | frontend (always) |
| Docker | any recent | **optional** — only for `BUS=redpanda` / TimescaleDB / Redis |

Everything else installs via pip/npm below. The default configuration
(`BUS=memory`, `LLM_MODE=scripted`) runs the **full demo with no Docker and no API keys**.

## Quick local run

The app runs as two local processes. Open two terminals from the repository root.
Docker and API keys are not required with the default offline configuration.

### Terminal 1 — backend

```powershell
# Windows PowerShell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m uvicorn app.main:app --reload --port 8000
```

```bash
# macOS / Linux
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m uvicorn app.main:app --reload --port 8000
```

### Terminal 2 — frontend

```powershell
# Windows PowerShell
cd frontend
npm install
npm run dev
```

```bash
# macOS / Linux
cd frontend
npm install
npm run dev
```

Then open **http://localhost:5173**. The backend API and interactive docs are available at
**http://localhost:8000** and **http://localhost:8000/docs**.

To run a scenario directly from a third terminal:

```bash
curl -X POST http://localhost:8000/api/scenarios/flood/start
# Other options:
# curl -X POST http://localhost:8000/api/scenarios/combined/start
# curl -X POST http://localhost:8000/api/scenarios/trip/start
# curl -X POST http://localhost:8000/api/scenarios/reset
```

## 1. Run the backend

```powershell
# Windows (PowerShell)
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"          # add ",agents" for google-adk/litellm extras
Copy-Item ..\.env.example ..\.env    # optional; defaults already work offline
python -m uvicorn app.main:app --reload --port 8000
```

```bash
# macOS / Linux (bash/zsh)
cd backend
python3.11 -m venv .venv         # or just: python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"          # add ",agents" for google-adk/litellm extras
cp ../.env.example ../.env       # optional; defaults already work offline
python -m uvicorn app.main:app --reload --port 8000
```

Verify it's up:

```bash
curl http://localhost:8000/api/health     # {"ok":true,...}
# interactive docs: http://localhost:8000/docs
```

### Run the backend tests

With the venv active (or `backend/.venv` created):

```bash
cd backend
pytest                 # full suite: city graph, simulator, conflicts, ingest, workflow
```

> `config.py` loads `.env` from `backend/`, then the repository root (`../.env`), and finally
> falls back to the checked-in `.env.example` — so with the offline defaults above, **the demo
> works even before you create a `.env`**.

## 2. Run the frontend

New terminal (leave uvicorn running):

```powershell
# Windows
cd frontend
npm install
npm run dev             # http://localhost:5173
```

```bash
# macOS / Linux
cd frontend
npm install
npm run dev             # http://localhost:5173
```

Vite proxies `/api` and `/ws` to `http://localhost:8000`, so keep the backend running on
port 8000. A production type-check + bundle is `npm run build` (runs `tsc -b` first).

## 3. Trigger the demo

**Option A — in the UI (recommended):** open http://localhost:5173 and press **Combined**
in the bottom bar. You'll watch the whole pipeline stream over the WebSocket:

detect → plan → negotiate → critic (fails → revises) → verified → **human Approve**
→ Execute, with the 3D twin updating live and a *time to verified plan* metric.

**Option B — from the terminal:**

```bash
curl -X POST http://localhost:8000/api/scenarios/combined/start
```

Other scenario endpoints: `/api/scenarios/flood/start`, `/api/scenarios/trip/start`,
`/api/scenarios/reset` (POST). UI buttons map to the same endpoints.

**Try the what-if branch:** press **What-if ↯** in the UI bar — it replays
"clear the flood + restore S2" *in the simulator only* (never the twin) and switches the
3D view to the ghost branch.

## 4. (Optional) Full infrastructure stack

Only needed to flip `BUS=redpanda` or persist to TimescaleDB:

```powershell
# Windows
docker compose up -d
Get-Content backend\app\db\schema.sql | docker compose exec -T timescale psql -U twin -d chronotwin
# then set BUS=redpanda in ..\.env and restart uvicorn
```

```bash
# macOS / Linux
docker compose up -d
docker compose exec -T timescale psql -U twin -d chronotwin < backend/app/db/schema.sql
# then set BUS=redpanda in ../.env and restart uvicorn
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ECONNREFUSED :8000` from the UI | backend isn't running — start uvicorn first |
| Frontend loads but no live updates | check the **LIVE/OFFLINE** dot in the header; `/ws` proxy needs uvicorn on 8000 |
| Port already in use | run uvicorn on another port and change the Vite proxy target in `frontend/vite.config.ts` |
| `pip install` picks old Python | use `python -m venv` with an explicit 3.11+ interpreter; check `python --version` |
| Redpanda connection errors | stay on the default `BUS=memory`, or `docker compose up -d` |

## Repository layout

```
chronotwin/
├── docker-compose.yml
├── .env.example
├── backend/app/
│   ├── main.py            FastAPI app + startup wiring
│   ├── config.py          settings
│   ├── models.py          Pydantic domain models
│   ├── db/                schema.sql + asyncpg pool
│   ├── city/              graph builder + cascade tracer
│   ├── sim/               state, engine, scenarios
│   ├── ingest/            bus, validator, trust, aggregator, anomaly, api
│   ├── agents/            orchestrator, specialists, negotiator, critic, workflow, llm
│   ├── tools/             power, traffic, emergency, plan (read vs mutate split)
│   ├── api/               incidents, plans, timeline, scenarios, ws
│   └── tests/             pytest
├── frontend/              Vite + React + TS + Three.js
│   └── src/               App, TwinScene, panels, api client, WS hook
└── README.md
```

## Demo story

Flood hits underpass **U1**, substation **S2** trips, junctions **J2–J5** go dark, the detour is
dark too, and ambulance **A1** bound for hospital **H1** is delayed. ChronoTwin traces the cascade,
the Power / Traffic / Emergency agents propose, a seeded conflict is resolved by the Negotiator,
the Critic rejects the first plan and the Revision agent fixes it, the operator approves, and the
Chrono timeline shows before / after / what-if.

## Modes

| Knob | Values | Effect |
|---|---|---|
| `BUS` | `memory` \| `redpanda` | in-process `asyncio.Queue` vs Kafka topics |
| `LLM_MODE` | `scripted` \| `ollama` \| `gemini` \| `claude` | deterministic replay vs local vs live |
| `LLM_CALL_BUDGET` | int | per-run cap proving "LLM calls scale with incidents, not data" |

For live models: set `LLM_MODE=gemini` + `GEMINI_API_KEY` (or `claude` + `ANTHROPIC_API_KEY`),
and `pip install -e ".[agents]"`. For a local model: `LLM_MODE=ollama` against `OLLAMA_BASE_URL`.

## Safety

Mutating tools are never registered directly with an agent. Agents submit `Action` proposals via
read/estimate tools only; the Critic verifies the joint plan in simulation, `HIGH`-impact actions
require an operator approval in the UI before `POST /api/plans/execute` writes to the twin, and
every step lands in the `action_log` (`GET /api/plans/action_log`).
#   C h r o n o C i t y  
 