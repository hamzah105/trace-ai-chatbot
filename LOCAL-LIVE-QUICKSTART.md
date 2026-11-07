# OOMP + TRACE: local live quickstart

Use the approved `trace-live` profile at `D:\os-trace-live-1108`. Its existing
owner, credentials, database and grants are preserved. A one-time private local
handoff selects that profile for this TRACE checkout; other installations remain
unchanged. The local launcher and selection are installed only with owner approval.

## Two terminals

Open fresh PowerShell terminals so old manually exported settings do not override
the approved connection. Terminal 1:

```powershell
oomp start
```

Terminal 2:

```powershell
cd 'D:\Desktop\VU BS-CS\CS619\TRACE'
.\.venv\Scripts\Activate.ps1
uvicorn backend.app:app --reload
```

Use TRACE's own activation. `python` and `uvicorn` must resolve from TRACE's
`.venv\Scripts`; do not inject OOMP's site-packages with `PYTHONPATH`. The private
handoff transfers connection settings and existing secret references, never Python
import paths. No token, owner ID, Mongo URI or repeated setup prompt is needed.

Open `http://127.0.0.1:8000/health` and then `http://127.0.0.1:8000/login.html`.
Sign in using the existing approved TRACE owner account. No account or password
is created by this integration, and another user's login cannot switch the pinned
memory owner. Browser/OAuth login and final model answers require manual testing.

## Fictional cross-session check

In a new TRACE session, send `I am developing a project called LUMENLOCAL.`.
After the completed interaction is approved and published, create another session
and ask `What is my LUMENLOCAL project?`. Inspect evidence/provenance separately
from the model's answer. A running worker or HTTP200 alone does not prove recall.
Optional follow-ups can state a fictional alias, response preference, tentative
relocation and later correction. An unsupported pet question should retain
uncertainty. This walkthrough creates new fictional interactions; do not backfill
private historical conversations.

The normal chatbot answer path uses TRACE's configured local model. The setup and
automated health checks do not request model inference or download weights.

## Status and shutdown

```powershell
oomp status
oomp doctor --full
oomp stop
```

Stop the TRACE test/development server with Ctrl+C in Terminal2. `oomp stop`
authenticates and stops only the selected managed supervisor and its children.
It preserves the profile, data, credentials and one-time connection configuration.
`oomp up`, `down`, explicit profile options and existing diagnostics remain available.

If no setup exists, `oomp start` opens a guided wizard in an interactive terminal.
It detects the selected project/Python, prompts for a missing owner ID, validates
only that ID against the selected users collection, presents read-only or approved
publication authority, and requests approval before creating files or credentials.
It never chooses a different user, rebinds an existing profile or rotates secrets.

## Troubleshooting and boundaries

An `on_startup` Router error indicates an incompatible/mixed web stack. The
measured compatible TRACE environment is FastAPI0.115.0, Starlette0.38.6,
Uvicorn0.54.0, Pydantic2.14.1 and MCP2.3.0. TRACE's own `pip check` passes. The
reported error was reproduced when OOMP's Starlette1.10.0 preceded TRACE on the
import path; do not reinstall an already consistent environment unnecessarily.

Invalid signatures, file permissions, changed profile bindings or conflicting
explicit settings fail closed. The ignored `.oomp.local.json` contains signed
references, not copied credential values. Do not share private profile/configuration
files, print secrets or commit them. Keep `.env` unchanged. A changed local profile
requires a new reviewed handoff rather than silent owner or grant changes.

Approved signed connection settings take precedence over legacy OOMP defaults in
`.env`. A different dotenv owner or conflicting inherited process settings are
rejected. Other TRACE dotenv settings continue to load normally. The selected
MongoDB configuration stays unchanged; only the publisher's in-memory `localhost`
reference is converted to literal loopback for its existing admission check.

The default selection is private at
`%LOCALAPPDATA%\OOMP\startup\selection.json`. The local `oomp.cmd` launcher uses
the existing user Scripts directory; setup changes neither PATH nor installed
packages. Existing profile/credential bytes remain unchanged.

## Executed verification: 8 November 2026

The exact activated reload command returned `/health` 200 after database readiness
and application startup. Its owned test server was stopped and port 8000 released.
Bare OOMP start/status/stop and full doctor were exercised; OOMP was left running
with all three managed services ready. Full doctor: 26 PASS, 0 WARN, 0 FAIL,
5 NOT TESTED. Focused checks: 94 unique OOMP passes and 62 TRACE passes, three
service-dependent TRACE tests deselected, no unexpected final skips. An earlier
incorrectly selected physical-Mongo test was blocked before connection; that failed
safety phase is preserved and excluded from acceptance. The corrected collection
was verified before execution with stronger fail-closed monitoring.

Browser login/OAuth and final cross-session model answers remain manual checks.
No model generation/download or private historical-chat backfill was performed.

This is one trusted local owner in an isolated profile. The general multi-principal
scheduler limitation remains open. Legacy source reads retain tenant/namespace
scope. No broad multi-user, remote-host, crash-resolution or production claim is made.
