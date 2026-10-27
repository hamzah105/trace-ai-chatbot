# Stage 8 completion report

Client date: 2026-10-27. **216 primary tests passed in 49.05s**, preserving all **134** earlier tests and adding **82** Stage 8 cases. Pytest separately reports **55 passing unittest subcases**. One upstream multipart deprecation warning remains. Actual MCP, isolated MongoDB persistence and two live llama3 smoke calls succeeded.

1. **TRACE workspace.** Implementation was confined to D:\Desktop\VU BS-CS\CS619\TRACE. The installation at D:\Desktop\OOMP was inspected and invoked as an independent application, without importing its Python core into TRACE or modifying its source.

2. **Git baseline.** TRACE was clean on main at 6976c5117e8015ebd3e0ee11fdceb2cfd8e87d2d, Complete TRACE Phase 3 analytics and session finalization. OOMP was clean at bc145c5a16b9b42d6bb6138e49da7caf87571120, Implement OOMP Stage 7. Before-edit manifests record tracked-file hashes and dependency versions.

3. **Files created (25).** Eight services: backend/services/chat_orchestrator.py; oomp_client.py; oomp_config.py; oomp_context.py; oomp_contracts.py; oomp_diagnostics.py; oomp_publisher.py; oomp_security.py. Added requirements-oomp.txt, requirements-dev.txt and pytest.ini. Tests: tests/conftest.py, stage8_support.py, test_oomp_client.py, test_oomp_context.py, test_oomp_end_to_end.py, test_oomp_feedback.py, test_oomp_publisher.py and test_oomp_security.py. Documentation: docs/oomp-integration.md, oomp-security.md, stage8-validation.md and this report. Templates: docs/examples/oomp-server.template.json and oomp-writers.template.json.

4. **Files modified (10).** .gitignore; README.md; sample.env; requirements.txt; backend/app.py; backend/routes/auth.py, chat.py and feedback.py; backend/services/ollama_service.py; frontend/index.html. The frontend change clears the optional owner credential on logout; there is no redesign. Session services/routes, analytics modules and original tests were not rewritten.

5. **Original test baseline.** Before production edits, python -m unittest discover -s tests -v passed 134 tests in 5.344s. Existing tests use mocks and Node checks rather than a production database/model. The working original environment used FastAPI 0.115.0 despite the older declared pin.

6. **SDK/client configuration.** Official mcp/mcp-types 2.3.0 runs in TRACE's separate environment over authenticated loopback Streamable HTTP. The optional requirements file does not install OOMP. SDK-required AnyIO/Pydantic/uvicorn compatibility and the existing pandas NumPy ABI are explicit. An import-blocking subprocess verifies that default-off execution needs neither MCP/httpx2 nor OOMP source.

7. **Connectivity.** Actual SDK Client discovery and tool calls reach a separate OOMP process over TCP, using protocol 2026-07-28. There is no custom JSON-RPC implementation or embedded OOMP server. Each operation closes its own client/transport lifecycle. Runtime data is separate from OOMP's source checkout.

8. **Tool mapping.** Uses actual memory.retrieve parameters: query, mode, max_results, token_budget, allow_degraded and graph_depth=0. SDK discovery validates arguments/output schemas, followed by bounded local packet validation. memory.status provides diagnostics; memory.ingest provides authorized publication. No caller-supplied scope parameter or model-selected tool workflow is introduced.

9. **Prompt composition.** Enabled mode separately labels the current question, recent transcript, historical evidence/provenance and feedback guidance. Historical claims remain untrusted JSON data rather than recent utterances or policy. The complete MCP envelope is not inserted. Nonpositive relevance and whole objects exceeding the prompt cap are omitted; failures return the original prompt.

10. **Latest-eight preservation.** The limit stays exactly eight with the original chronological order and feedback guidance. Disabled prompt bytes match the original function from 6976c51 on identical history. The central enabled test retains all eight latest interactions alongside the early fact. An enabled recent prompt exceeding capacity is rejected rather than silently clipped.

11. **Ollama integration.** Keeps generate_response(prompt), /api/generate, llama3, temperature and num_predict. Enabled mode adds configured num_ctx; the successful response schema stays unchanged. Separate live smoke calls returned TRACE Stage 8 ready., taking 75.895s off and 70.405s enabled. Deterministic historical recall uses a model mock and makes no answer-accuracy claim.

12. **Modes.** off is default and makes no MCP call or publication. retrieve adds deterministic host retrieval only. retrieve_and_ingest also stages consented completed events for an explicitly launched publisher. Remote fields cannot elevate mode. No worker or history import starts during application import.

13. **Authorization and scope.** Trusted configuration pins one TRACE owner and one OOMP principal/tenant/namespace. Enabled private routes require a verified owner login cookie or separate local owner key, alongside stored ownership/lifecycle checks. A submitted user_id does not select an OOMP grant.

14. **Authentication limitations.** Single-owner local development only. Exact Host/Origin and loopback checks cover private history and analytics too. HttpOnly/Strict cookies expire after eight hours and clear on logout/account switching; copied stateless tickets are not individually revoked before expiry. Broader baseline authentication is not rewritten, and public/proxy deployment is unsupported.

15. **Trusted ingestion.** Explicit full mode plus verified owner activity stages consent. Events derive from actual successful Mongo records, with separate user, assistant and submitted-feedback roles. The model has no signer, approval or storage tool. OOMP extraction policy remains authoritative; assistant output is not promoted into user-profile memory.

16. **Host approval.** The client implements the documented Stage 7 HMAC-SHA256 wire envelope without importing OOMP. It binds exact payload, principal/scope/source policy, nonce and a sixty-second lifetime. Host secrets remain separate from bearer/owner keys. Actual OOMP accepted all three source roles and rejected a modified signed payload. This is deliberate application-policy approval, not proof of a per-event human click.

17. **Mongo outbox and retry.** Embedded per-chat completion/consent/exclusion and role delivery state reference authoritative records without duplicating message bodies or creating a new memory database. Conditional updates use thirty-second leases/fence tokens. Five automatic attempts use bounded backoff; permanent authorization/conflict/policy failures stop. An explicit worker reconciles consented gaps and drains bounded batches.

18. **Idempotency.** Stable IDs/keys hash pinned owner, persisted Mongo _id and role within OOMP Identifier limits. Retries reconstruct the same BSON-normalized payload with fresh approval. Acceptance-before-ack and failed acknowledgement replay through Stage 2 idempotency. Conflicting evidence stops. Actual outage/restart/replay left exactly one logical OOMP event.

19. **Feedback.** Original ownership, validation, active-session and submit-once guards remain. Feedback publication is scheduled only after the original successful Mongo update. Scheduling failure cannot undo or block valid feedback; reconciliation repairs it. Classification values and metric formulas are unchanged.

20. **Session lifecycle.** Creation, switching, owned history, pending-feedback guards and permanent finalization are retained. Ended, wrong-owner and pending-feedback requests reject before MCP/generation. Cross-session recall is owner-only and explicitly labeled. Existing process-local session_lifecycle still requires one TRACE application worker.

21. **Analytics verification.** All eight backend/analytics files match baseline hashes. Original routes, charts, tables, snapshots, normalization and Node frontend tests pass. Integration metadata leaves normalized metrics unchanged. response_time_seconds retains prompt-assembly-plus-generation timing; enabled retrieval contributes to it, while delivery runs separately.

22. **Outage behavior.** Actual connection refusal falls back without losing chat/feedback state. Stalls are deadline bounded; malformed, oversized and redirected responses fail safely. Invalid credentials produce authorization_failed and never trigger a broader grant. Publication retains retry state during actual server outage and recovers after restart.

23. **Historical demonstration.** A synthetic 106-interaction history contains the early OOMP project fact followed by 105 unrelated turns. Baseline context contains turns 98–105 and lacks the fact. After real signed MCP publication and explicit external extraction, FastAPI chat retrieves the canonical fact with its original Mongo source ID and includes all eight recent turns. Captured prompts/diagnostics are in ignored data/stage8-artifacts/long-history-demo.json. Baseline answer failure or improved accuracy is not claimed.

24. **Prompt injection.** JSON encoding, separate labels, untrusted-data instructions and proof validation keep source text out of application policy. No model tool execution can gain signing, erasure or scope authority. A single generate prompt cannot guarantee semantic immunity of an LLM answer; that limit is documented. Operation-local SDK log filtering prevents parser tracebacks from exposing remote validation input, tested against an actual malformed response.

25. **Resource bounds.** Default MCP deadline five seconds, maximum fifteen; four concurrent calls; 1 MiB streamed and 512 KiB structured responses. Default evidence budget 1200 conservative UTF-8 units, five results, prompt cap 7000 bytes, num_ctx 8192, reserve 512 plus 256 overhead. Whole evidence is omitted rather than cut. Batches are capped at 100. These are not exact-tokenizer or hard real-time guarantees; first optional SDK import and CPU scheduling add local overhead.

26. **New test count.** 82 primary cases in six modules cover default-off independence, actual SDK calls, owner/scope failures, packet/provenance accounting, injection/log suppression, feedback/session/analytics behavior, signatures/roles, duplicate/conflicting delivery, real Mongo persistence, reconciliation, exclusion, network limits, concurrency and actual outage/restart.

27. **Total tests.** Final full pytest: 216 passed in 49.05s, plus 55 passing unittest subcases and one warning. Subcases are not counted as new primary tests. Verbose and JUnit evidence are under ignored data/stage8-artifacts.

28. **Previous regressions.** All 134 original tests pass. All thirteen original test files are byte-for-byte unchanged. Node frontend tests execute rather than skip. All original analytics files remain unchanged. Exact disabled prompt comparison and public successful response shape have dedicated tests.

29. **Live Ollama status.** Existing tags included llama3:latest and embeddinggemma:latest. Two actual llama3 generate smoke calls succeeded with synthetic input and no download. Live historical-answer accuracy, comparative recall quality and embedding inference were not measured.

30. **Real MCP results.** TRACE SDK clients use a separate installed OOMP server, not direct Python handlers. Authenticated discovery/status/retrieve/ingest, source roles, tamper rejection, wrong-scope credential rejection, independent loops, actual stop/restart and replay passed. Subprocesses/listeners were cleaned up. Desktop-host interoperability is not certified.

31. **Errors and warnings.** No final failures/errors/skips. One unsuppressed Starlette multipart PendingDeprecationWarning remains. During development, live-model resource contention caused an external fixture startup timeout; final tests ran afterwards with forty-five-second fixture startup allowance, without enlarging production operation deadlines. Browser visual acceptance and production deployment remain manual.

32. **Windows manual testing.** Follow [the integration guide](oomp-integration.md): install optional requirements, provision matching secrets/owner/grants, launch OOMP server/worker and TRACE separately, run diagnostics, log in as owner, submit feedback, switch/finalize sessions, stop/restart OOMP and drain publication, and inspect analytics. [Validation](stage8-validation.md) supplies exact commands. Review a dry-run before approving any real legacy history.

33. **Documentation.** Updated README/sample.env; added integration, security, validation and this report, plus two valid non-secret JSON templates. They cover independent repositories, optional install, modes, owner authentication, actual wire grants, budgets, retries, privacy/recovery windows, Windows operation and remaining limits. Student/supervisor attribution is preserved.

34. **Security constraints.** Dedicated TRACE-linked source proof only. Correct OOMP credential provisioning remains primary server authority because Stage 7 emits no signed tenant attestation. Host-only keys, no OOMP imports, no public/proxy/TLS or general multi-user profile, no encryption or universal injection guarantee, no model erasure/approval, no automatic real-history import and no distributed-transaction claim. Exclusion cannot recall accepted/in-flight data.

35. **Stage 9 prerequisites.** User inspection first. Then separately define consented datasets, frozen off/retrieve/full configurations, model/tokenizer/context policy, timing boundaries and repeated paired measurements. Distinguish supplied-prompt recall from answer accuracy, include outage/resource costs and preserve provenance/role/privacy constraints. No comprehensive benchmark is implemented here.

36. **Git status.** TRACE remains on main at 6976c51 with ten modified and twenty-five new files listed above. Credentials, .env, environments, databases/sidecars, artifacts and logs are ignored. No commit, push, remote creation, reset/history rewrite or global Git change. The working tree is left for review.

37. **OOMP unchanged.** Hash audit verifies all 120 tracked files and clean status against baseline; HEAD remains bc145c5. External CLI calls use -B/PYTHONDONTWRITEBYTECODE and test data resides outside its checkout. No OOMP source, tests, documentation, dependency environment or schema was modified.

38. **Stage boundary.** Only Stage 8 is implemented. No Stage 9 benchmarking, Stage 10 release work, general model tool framework, new chatbot model, replacement database or unrelated frontend/analytics work. Stop for user inspection/manual assessment; no automatic commit or push.