# Stage 8 validation

Client date: 2026-10-27. Primary workspace: D:\Desktop\VU BS-CS\CS619\TRACE. OOMP was a read-only external installation at D:\Desktop\OOMP.

## Baselines and exact results

| Check | Observed result |
| --- | --- |
| TRACE before edits | Clean main, 6976c5117e8015ebd3e0ee11fdceb2cfd8e87d2d |
| Original test command | python -m unittest discover -s tests -v |
| Original result | **134 tests passed in 5.344s** |
| OOMP before edits | Clean main, bc145c5a16b9b42d6bb6138e49da7caf87571120; Stage 7 report records 392 passing tests |
| Final complete command | .venv\Scripts\python.exe -m pytest -v |
| Final result | **216 passed in 49.05s**, plus **55 passing unittest subcases**, **1 warning** |
| New Stage 8 primary cases | **82**, in six dedicated test modules |
| Earlier regressions | All 134 primary tests still pass; 13 original test files have unchanged SHA-256 |
| Analytics preservation | All 8 backend/analytics files have unchanged SHA-256 |
| OOMP preservation | All 120 tracked files unchanged; HEAD and clean Git status unchanged |
| Official SDK | mcp/mcp-types 2.3.0; actual client reports protocol 2026-07-28 |
| Real transport | Separate external OOMP CLI process, authenticated loopback TCP Streamable HTTP |
| Mongo persistence | Real isolated local MongoDB test database, client close/reopen and replay passed |
| Compilation/dependencies | compileall, pip check, changed inline JS and analytics JS syntax checks passed |
| Diagnostic | Default-off administrative status succeeds without contacting MCP/Mongo |
| Live model | Existing local llama3 through /api/generate succeeded in both off and retrieve configurations |

The 55 unittest subcases are reported separately by pytest 9; they are not counted as 55 additional Stage 8 test functions. The original unittest baseline remains 134, and the new primary count is 82, for 216 total.

The final warning is Starlette 0.38.6's PendingDeprecationWarning requesting python_multipart rather than the older multipart import spelling. It is an upstream import warning, not a failed test, and was not suppressed. No final errors, failures or skips occurred.

The initial TRACE installation did not match all declared requirements: its working baseline used FastAPI 0.115.0, Pydantic 2.9.2 and AnyIO 3.7.1. SDK 2.3.0 needs AnyIO >=4.9, Pydantic >=2.12 and newer uvicorn. A separate TRACE environment was installed, with no OOMP or global-environment modification.

Final versions: Python 3.11.4; FastAPI 0.115.0; Starlette 0.38.6; Pydantic 2.14.1; PyMongo 4.17.0; NumPy 1.26.4; pandas 2.1.3; mcp/mcp-types 2.3.0; httpx2 2.16.0; AnyIO 4.15.1; sse-starlette 3.0.3; uvicorn 0.54.0; pytest 9.1.1.

## Executed synthetic scenarios

**Baseline and historical recall.** A synthetic owned conversation has 106 persisted interactions. Its early user source says the owner is developing OOMP, followed by 105 unrelated turns. The original prompt is compared byte-for-byte against the version from commit 6976c51. It contains turns 98–105 and no early fact. Explicitly approved publication sends the early event over the actual SDK/MCP client to a separate OOMP server; an explicitly run external worker extracts it. TRACE's actual FastAPI /chat path then retrieves the canonical project evidence, validates original Mongo provenance and includes it with all eight recent interactions in the generation prompt. The response shape, mandatory pending feedback and bounded prompt remain correct. Model response is mocked for this deterministic scenario.

Actual prompts, the source interaction ID and measured diagnostics are recorded in ignored data/stage8-artifacts/long-history-demo.json. The test does not claim baseline LLaMA must answer incorrectly or measure an answer-accuracy improvement.

**Offline and invalid service.** Real connection refusal falls back to the original prompt without losing chat/feedback state. A stalled local HTTP endpoint exercises the total SDK deadline; oversized and redirected responses fail safely. Invalid actual MCP credentials produce authorization_failed without trying another grant. Malformed response/packet tests reject forged content/counts/scope fields, and an actual malformed remote JSON value is absent from SDK logs and tracebacks.

**Owner and scope.** Missing/forged owner credentials, wrong request owner, invalid Host/Origin, other-owner history/analytics and foreign feedback rows are denied before memory use. Verified existing password login issues the owner cookie; logout/account switching clears it; tampering fails. Cross-session recall works for the pinned owner. An actual MCP token intentionally mapped to a foreign OOMP tenant returns foreign evidence; TRACE rejects its foreign Mongo proof before the model/logs. Independent concurrent SDK calls own distinct loops/lifecycles.

**Durable delivery.** Roles, signatures and feedback gating use actual persisted Mongo identities. Real OOMP accepts user/assistant/feedback events with correct role attribution, rejects a modified signed payload and stores one logical event on equal retry. Another test stops the actual OOMP server, observes durable retry state, restarts the same external server/database, replays delivery and verifies exactly one event. Concurrent claims, acceptance-before-ack uncertainty, failed local acknowledgement, bounded attempts and exhausted leases are also exercised. A separate unique real MongoDB database proves outbox state persists after a client reconnect; only that synthetic database is dropped.

**Recovery and privacy.** Reconciliation repairs consented completed gaps without importing legacy or failed staged rows. Explicit dry-run backfill pages only the pinned owner and reports invalid rows. Exclusion survives replay/backfill/reconciliation. Feedback is never queued as completed before submission. Scheduling failure after feedback does not undo valid feedback; reconciliation repairs it.

**Phase 3.** Pending feedback blocks generation before MCP; ended sessions and wrong ownership still reject requests. Feedback remains submit-once, finalization remains idempotent and read-only, and integration metadata does not change normalized metrics. All existing analytics, routes and Node-based frontend tests pass unchanged.

## Live Ollama smoke check

The already installed local service reported llama3:latest and embeddinggemma:latest. No model was downloaded and no embedding inference was required.

Using TRACE's existing generate_response function and a synthetic instruction to reply briefly:

| Mode | Model/API | Result | Observed duration |
| --- | --- | --- | --- |
| off | llama3, /api/generate, original options | TRACE Stage 8 ready. | 75.895s |
| retrieve | llama3, /api/generate, num_ctx=8192 | TRACE Stage 8 ready. | 70.405s |

These two smoke calls validate the unchanged model interface and enabled context option. They do not demonstrate complete live-model historical recall, a speed improvement or statistical accuracy. The deterministic recall test uses a mock response. Synthetic live output is recorded in ignored data/stage8-artifacts/live-ollama.json.

A development test startup timed out while live model inference competed for local resources. Final automated validation ran after that inference; external fixture startup allows 45 seconds, while production MCP operation deadlines remain at their configured five-second default. No final test was skipped or weakened to claim a passing network result.

## Reproduce on Windows

~~~powershell
Set-Location "D:\Desktop\VU BS-CS\CS619\TRACE"
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -v
.\.venv\Scripts\python.exe -m compileall -q backend tests
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m backend.services.oomp_diagnostics
.\.venv\Scripts\python.exe -m pytest tests\test_oomp_end_to_end.py tests\test_oomp_publisher.py -v
~~~

The optional external executable defaults to D:\Desktop\OOMP\.venv\Scripts\python.exe. Override TRACE_TEST_OOMP_PYTHON for a different installation. Tests call its CLI with -B and keep synthetic SQLite/config files under TRACE's ignored test-artifact area. No OOMP Python core imports occur in the application.

For manual browser acceptance, follow [integration setup](oomp-integration.md): provision matching credentials, pin an actual existing owner, start OOMP/server/worker and TRACE separately, log in as that owner, submit mandatory feedback, switch sessions and inspect evidence/analytics. Test off/retrieve/full mode explicitly. Stop OOMP to check fallback, restart and drain pending publication. Perform legacy backfill dry run before deliberately approving any real history. No real history was imported by this milestone.

A full visual browser pass, interactive logout during a live desktop session, public deployment, arbitrary multi-user mapping, proxy/TLS setup and live-model comparative recall remain unverified. There is no Stage 9 benchmark result.

## Evidence and scope audit

Ignored local artifacts include baseline.json, baseline-tests.txt, final-tests.txt, final-tests.xml, final-audit.json, long-history-demo.json and live-ollama.json under data/stage8-artifacts. Some PowerShell test logs use UTF-16. They contain synthetic data and are not Git additions.

The final source audit verifies OOMP's 120 tracked files and clean Git status against the before-edit manifest; all original TRACE tests and analytics sources also match their recorded hashes. No commit, push, remote, history rewrite or global Git change occurred. Implementation stops at Stage 8 for user inspection. See the [38-item report](stage-8-report.md).