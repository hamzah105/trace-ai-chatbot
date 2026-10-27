# TRACE.AI

TRACE.AI is a local multi-turn chatbot and response analytics project for the CS619 Final Year Project. It uses FastAPI, MongoDB, Ollama with LLaMA 3, and a static HTML/CSS/JavaScript frontend. Phase 1 established registration, chat, and MongoDB storage; Phase 2 added owned sessions and feedback controls; Phase 3 adds session analytics and end-of-session snapshots.

**Student:** M Hamzah Shoaib (BC230200900)\
**Supervisor:** Miss Neelam Alam\
**Course:** CS619, Virtual University of Pakistan

## Features

- Local registration and login, with optional Google OAuth.
- User-owned chat sessions with history, switching, and up to the latest eight interactions included as model context.
- Ollama-generated responses with timing, rule-based topic labels, and mandatory per-response feedback: rating 1–4, correctness (Correct / Partial / Incorrect), and length (Short / To the Point / Lengthy).
- Input validation and a backend guard that prevents another chat until feedback is submitted.
- An offline-capable analytics dashboard with eight overview cards, seven charts, and six tables. Dashboard assets are served locally without CDNs; MongoDB and the backend must be available. Google OAuth requires internet access, as does the initial Ollama model download.
- Owned, chronological full-history analytics with normalized interaction records and phases. Six rule-based topics are Machine Learning, Deep Learning, Healthcare AI, Power Systems, E-commerce AI, and General. Phase assignment uses interaction position: for one interaction it is Start; for two, Start and End; otherwise thirds map to Start, Middle, and End.
- Feedback metrics score Correct as 1, Partial as 0.5, and Incorrect as 0. Weighted accuracy and strict-correct rate are reported separately. Only feedback marked submitted with valid values contributes to feedback metrics; missing or invalid values are excluded. Rating, length, and response-time metrics use their own valid-value counts.
- Ending a session stores a versioned final analytics snapshot with its overview and metrics. Every interaction must have strictly submitted feedback; an empty session can be ended. Ended sessions reject chat and feedback writes. Repeating an end request is idempotent. Existing valid snapshots are authoritative; legacy ended sessions without a valid snapshot remain readable with analytics calculated dynamically, without rewriting or backfilling stored data. Tables and charts are regenerated from data and are not stored as HTML or SVG.

### Phase 3 requirements (FR14–FR22)

| Requirement | Implementation |
|---|---|
| FR14 — Owned analytics data | `data_service.get_session_analytics_data` retrieves the complete history for an owned session and normalizes it for analytics. |
| FR15 — Topic classification | `topic_service.classify_topic` assigns one of six rule-based topics. |
| FR16 — Session phases | `data_service.phase_for_position` assigns N=1 to Start; N=2 to Start and End; for larger sessions, positions through one third are Start, through two thirds Middle, and the remainder End. |
| FR17 — Core metrics | `metrics.compute_session_metrics` computes pure session metrics over normalized interactions. |
| FR18 — Correctness evaluation | `metrics.CORRECTNESS_SCORES` defines Correct=1, Partial=0.5, Incorrect=0; metrics report weighted accuracy and strict-correct rate separately. |
| FR19 — Analytics tables | `tables.build_session_tables` creates six display tables from normalized data and metrics. |
| FR20 — Analytics charts | `charts.build_session_charts` creates seven chart specifications. |
| FR21 — Dashboard | `dashboard.build_session_overview`, analytics routes, and local `frontend/analytics.*` provide the overview and dashboard data/display. |
| FR22 — Session finalization | `finalization.finalize_session`, snapshot/lifecycle services, session/chat/feedback routes, and frontend controls finalize a session and block later chat or feedback writes. |

Analytics follows this flow: retrieve and normalize the owned full history, compute metrics and overview, then conditionally update the active session with its final snapshot and ended status. The stored `final_analytics` snapshot contains `version`, `finalized_at`, `interaction_count`, `overview`, and `metrics`; the session also receives `status: ended`, `ended_at`, and an updated `updated_at` value. Pending feedback or computation failure leaves the session without a new snapshot.

## Architecture and data

`backend.app` serves the API and static frontend. MongoDB uses the existing `users`, `sessions`, and `chat_history` collections. Analytics code separates owned data retrieval and normalization (`data_service.py`), pure metrics (`metrics.py`), table and chart projections (`tables.py`, `charts.py`), dashboard overview (`dashboard.py`), and finalization/snapshot handling. The frontend dashboard is in `frontend/analytics.html` with its local JavaScript and CSS.

Session finalization uses a process-local per-session reentrant lock and a conditional MongoDB update. Run a single Uvicorn worker: this coordination does not cover multiple processes or external direct MongoDB writers.

## Setup

Requirements: Python 3.11 or later, MongoDB, and Ollama. From the project root:

```powershell
py -m pip install -r requirements.txt
```

Copy `sample.env` to `.env` and adjust local settings if needed. The sample contains MongoDB and Ollama defaults. Keep `.env` out of version control. Start MongoDB, then download and start the model once:

```powershell
ollama run llama3
```

Start the application from the project root:

```powershell
py -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload
```

Open `http://127.0.0.1:8000` or `http://127.0.0.1:8000/index.html`. The root redirects to the login page. The dashboard is available at `http://127.0.0.1:8000/analytics.html`; API documentation is at `http://127.0.0.1:8000/docs`.

Google OAuth is optional; local login works with Google settings blank. To enable Google login, configure a Google OAuth web client, set its client ID and secret, and use this exact redirect URI:

```text
http://127.0.0.1:8000/auth/google/callback
```

Set the authorized origin to `http://127.0.0.1:8000`. Configure `GOOGLE_REDIRECT_URI` in `.env` to the exact callback above. Set `GOOGLE_OAUTH_STATE_SECRET` to a long random secret and never commit it or the OAuth client secret. Keep the app on the `127.0.0.1` origin for this redirect configuration.

## Main API routes

Session retrieval, history, and analytics reads below require the `user_id` query parameter. Session retrieval at `/sessions/{session_id}` requires it; omitting it is a validation error. Listing sessions uses `user_id` in the path. This retains the existing supplied-user-ID ownership contract; it does not add a new authentication architecture. Create/end and chat/feedback requests carry their user/session identifiers in their request bodies.

| Method and path | Purpose |
|---|---|
| `POST /register`, `POST /login` | Local account registration and login |
| `GET /auth/google/status`, `/auth/google/login`, `/auth/google/callback`, `/auth/google/session` | Optional Google OAuth flow |
| `POST /sessions/create` | Create an owned session |
| `GET /sessions/user/{user_id}` | List a user's sessions |
| `GET /sessions/{session_id}?user_id=...` | Retrieve an owned session |
| `GET /sessions/{session_id}/messages?user_id=...` | Retrieve owned session history |
| `POST /chat` | Generate and store a response |
| `POST /feedback` | Submit feedback for an interaction |
| `POST /sessions/{session_id}/end` | Finalize and end a session |
| `GET /analytics/session/{session_id}?user_id=...` | Retrieve normalized session analytics data |
| `GET /analytics/session/{session_id}/metrics?user_id=...` | Retrieve session metrics |
| `GET /analytics/session/{session_id}/tables?user_id=...` | Retrieve six analytics tables |
| `GET /analytics/session/{session_id}/charts?user_id=...` | Retrieve seven chart specifications |
| `GET /analytics/session/{session_id}/dashboard?user_id=...` | Retrieve the complete dashboard payload |
| `GET /health` | Check backend availability |

Session errors distinguish missing sessions (404), wrong owners (403), pending feedback or ended-session write attempts (409), database unavailability (503), and analytics computation failures (500). Finalization does not save a snapshot when feedback is pending or computation fails.

## Checks

Run the automated suite with:

```powershell
py -m unittest discover -s tests -v
```

Analytics tests use mocked database and Ollama boundaries and do not require external services. Frontend JavaScript checks require Node.js. These commands describe the available checks; results depend on the current environment.

See [the Phase 3 Part 5 acceptance report](docs/phase3-part5-validation.md) for test coverage, the manual browser/Compass scenario, API examples and known limitations.

## Attribution

Developed by **M Hamzah Shoaib (BC230200900)** for **CS619, Virtual University of Pakistan**, under the supervision of **Miss Neelam Alam**.


## Optional OOMP memory (Stage 8)

TRACE can use the independent OOMP installation through the official MCP SDK 2.3.0 over authenticated loopback Streamable HTTP. Default TRACE_OOMP_MODE=off keeps the original latest-eight prompt, generation API, feedback rules and analytics. No MCP dependency or request is needed in that mode.

The retrieve mode adds validated historical evidence before generation. The retrieve_and_ingest mode also queues explicitly approved, successfully persisted user/assistant/feedback events for a separately launched publication worker. MongoDB remains authoritative; the embedded outbox stores references and retry state, not a second memory database. OOMP's own worker extracts/indexes accepted events separately.

Memory-enabled operation is a pinned single-owner local development profile. Successful existing owner login issues a short-lived HttpOnly owner cookie; local administrative clients can use a separate owner key. Submitted user IDs alone never authorize memory. Other owners are rejected; history/analytics are protected too. This is not production multi-user authentication.

~~~powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-oomp.txt
.\.venv\Scripts\python.exe -m backend.services.oomp_diagnostics
~~~

Follow [installation and Windows operation](docs/oomp-integration.md), [security and privacy](docs/oomp-security.md), [executed validation](docs/stage8-validation.md) and the [38-item Stage 8 report](docs/stage-8-report.md). Configuration starts disabled; templates contain environment-variable names, never live credentials.

Stage 8 validation: **216 tests passed**, preserving all 134 earlier tests and adding 82 integration/security cases. The pytest run also reports 55 passing unittest subcases separately. Actual external MCP, isolated MongoDB persistence and two synthetic live llama3 generation checks passed. One upstream Starlette multipart deprecation warning remains. No improved-answer-accuracy claim is made. OOMP source remains unchanged; no Stage 9/10 work, commit or push.
