# TRACE + OOMP integration (Stage 8 and opt-in P4B)

TRACE remains a FastAPI/MongoDB/Ollama application. OOMP remains an independent external product, installed at D:\Desktop\OOMP. TRACE imports no OOMP Python modules, copies no OOMP implementation and opens no OOMP database. Its optional client uses the official MCP SDK 2.3.0 over authenticated loopback Streamable HTTP.

The historical Stage 8 baseline was clean TRACE main 6976c51 (Phase 3 complete), with 134 passing tests. The independent OOMP Stage 7 installation was inspected read-only at bc145c5. See [validation](stage8-validation.md) for exact final results and [security](oomp-security.md) for the trust boundary.


P4B is an explicit optional retrieval API within the existing deployment modes. The latest-eight descriptions and Stage 8 service commands below describe the legacy API, which remains the default. For local P4B offline validation, use the [fictional adapter quickstart](oomp-p4b-fictional-quickstart.md); its reviewed controller blocks real MongoDB, model and external OOMP service access. Historical validation numbers below are not P4B results. Current measured results belong in [the P4B report](product-milestone-P4B-report.md).
## Deployment modes

| TRACE_OOMP_MODE | Behavior |
| --- | --- |
| off (default) | Original latest-eight prompt and model interface; no MCP call, import or publication. Optional SDK not needed. |
| retrieve | Deterministic MCP retrieval before eligible generation; no publication. |
| retrieve_and_ingest | Retrieval plus host-approved publication eligibility for newly completed owner interactions. An explicit separate TRACE publication worker delivers queued events. |

Remote chat fields cannot change these modes, credentials or scopes. Invalid enabled configuration fails private requests closed; /health retains its original response. With the default legacy retrieval API, infrastructure failures during retrieval fall back to the unchanged original prompt, with a sanitized diagnostic. Opt-in P4B uses the bounded context fallback described below. Authorization failures are reported distinctly and never trigger another credential or broader scope.

## Install in TRACE's environment

Use Python 3.11+ and the TRACE root:

~~~powershell
Set-Location "D:\Desktop\VU BS-CS\CS619\TRACE"
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
~~~

The baseline install has no MCP dependency. To enable integration:

~~~powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-oomp.txt
.\.venv\Scripts\python.exe -m pip check
~~~

requirements-oomp.txt adds SDK 2.3.0 and an SSE dependency constraint compatible with TRACE's FastAPI/Starlette versions. requirements.txt aligns FastAPI with the tested original environment (0.115.0), allows SDK-required Pydantic >=2.12 and uvicorn >=0.31.1, and constrains NumPy to the ABI supported by the existing pandas 2.1.3. The installed integration environment passed the complete earlier regression suite. Nothing is installed into OOMP's environment.

For tests, install requirements-dev.txt, which includes the optional client, pytest and mongomock. No models are downloaded. Existing MongoDB/Ollama configuration and ordinary .env loading retain their TRACE behavior.

## Pin the authorized owner

This is an explicit single-owner, single-machine development profile, not general multi-user production security.

Set TRACE_OOMP_OWNER_ID to the actual MongoDB user ID of the intended existing TRACE owner. Pin tenant, namespace and principal in trusted server configuration. The OOMP read credential must map to that same dedicated scope. Never derive these grants from an HTTP user_id or session_id.

Provision a separate random TRACE_OOMP_OWNER_KEY and TRACE_OOMP_READ_TOKEN, each URL-safe and generated from at least 32 random bytes. Keep values out of source, URLs, logs, templates and browser localStorage. A generated process-local value can be captured without displaying it:

~~~powershell
$env:TRACE_OOMP_OWNER_KEY = (& .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))")
~~~

Provision all other secrets through the same trusted local secret mechanism. Separate processes need the matching values in their own environments; a second terminal does not automatically inherit a first terminal's new environment variables.

A successful existing password login by the pinned owner, or the existing verified Google login handoff, issues an eight-hour HttpOnly, SameSite=Strict memory-owner cookie. The cookie carries a purpose-bound signature, expiry and pinned owner. The browser automatically sends it on the existing same-origin requests. Login as another user clears it. Logout clears it through the narrow /auth/oomp/logout route; the ordinary disabled-mode logout path makes no new request unless a prior memory-login flag exists.

Trusted local administrative/API clients can instead send X-TRACE-Memory-Key with the owner key. The header is a deployment credential, not a model field. Both methods require a loopback peer, exact configured Host and same Origin when present. Protected chat, feedback, session/history, user-profile and analytics requests cannot bypass this credential. Query/body owner selection must also match the pin; feedback rechecks the stored owner even when optional body fields are omitted.

Use exactly the configured origin, normally http://127.0.0.1:8000. The setting is TRACE_OOMP_TRACE_ORIGIN, distinguishing TRACE's origin from the external MCP URL. A localhost hostname, LAN client or reverse proxy is not automatically trusted. The supported app entry point is backend.app:app. The legacy backend.main entry has no owner-login workflow and fails memory-enabled chat closed.

## Run independent services

The external OOMP database is runtime data owned by OOMP, not a TRACE canonical-memory store. Use an explicitly selected runtime location outside both source repositories, for example %LOCALAPPDATA%\OOMP\trace-local.sqlite3. Do not modify OOMP source or initialize a database in its checkout during Stage 8.

For full mode, copy these non-secret examples into TRACE's ignored credentials directory:

- [OOMP server template](examples/oomp-server.template.json)
- [TRACE writer descriptors](examples/oomp-writers.template.json)

Set the server template's database field to the intended absolute runtime database path. The server contains a read-only grant and separate user/assistant writer grants. User and feedback reuse the same accurately attributed user grant with event_types ordered as user_message, feedback. All descriptor IDs, principal/scope/source policy, event-type order and environment names must agree exactly with the external server.

Initialize only the deliberately selected runtime database, then start OOMP separately:

~~~powershell
$runtimeDb = Join-Path $env:LOCALAPPDATA "OOMP\trace-local.sqlite3"
& "D:\Desktop\OOMP\.venv\Scripts\python.exe" -B -m oomp storage init --db $runtimeDb
& "D:\Desktop\OOMP\.venv\Scripts\python.exe" -B -m oomp mcp serve --config "D:\Desktop\VU BS-CS\CS619\TRACE\credentials\oomp-server.local.json"
~~~

For read-only deployments, use a read-only OOMP server profile/grant instead. The full template is intentionally privileged and is not TRACE's default configuration. The -B option avoids bytecode writes into the external checkout.

OOMP does not start its worker when an MCP client connects. In another appropriately configured process, run the existing worker explicitly:

~~~powershell
& "D:\Desktop\OOMP\.venv\Scripts\python.exe" -B -m oomp mind work --db $runtimeDb --tenant trace-local --namespace personal --poll-seconds 1
~~~

Supply the same explicit runtime path in each terminal. This worker owns OOMP extraction/indexing under the configured scope; durable MCP acceptance alone does not mean a new canonical memory already exists.

Start TRACE with its existing single-worker entry point:

~~~powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
~~~

Keep the original single-application-worker limit for session_lifecycle/finalization. No cloud deployment, tunnel, public listener or proxy trust is introduced.

## Retrieval, prompt composition and budgets (legacy API)

Each eligible /chat request first retains the original session ownership/status and pending-feedback guards. It obtains the same last-eight interactions and feedback guidance from MongoDB. Retrieval is controlled by the host before generation, never by an LLM tool decision.

The SDK client discovers the actual memory.retrieve schema, submits query, mode, max_results, token_budget, allow_degraded and graph_depth=0, then validates both the discovered output schema and its own bounded wire model. No requested tenant/namespace/principal is sent. The client owns a fresh async event loop and complete HTTP/SDK lifecycle inside each synchronous FastAPI worker call; it reuses no session across loops. Calls are capped at four concurrent operations and a configurable total deadline (default five seconds, maximum fifteen). Redirects are refused, environment proxies disabled, and response streaming bounded before JSON parsing.

The host checks context_packet UTF-8 accounting against the returned budget and memory list. It additionally binds each memory and path proof to real owner-linked MongoDB interaction/session records, expected source_system, role-specific event IDs and session hashes. Stage 7 responses do not attest tenant/namespace; the configured credential mapping remains primary authority. The Mongo checks catch foreign/unlinked evidence and misconfigured foreign credentials, rather than inventing a scope field the protocol does not return.

The memory-aware prompt separately labels current message, latest-eight session transcript, historical evidence/provenance and feedback guidance. It serializes data as JSON under explicit untrusted-data instructions. It does not insert old memories as newly spoken turns or concatenate a full MCP envelope. Cross-session evidence is explicitly labeled as such. Stored claims are not verified truth.

Defaults are:

| Setting | Default / bounds |
| --- | --- |
| TRACE_OOMP_EVIDENCE_BUDGET | 1200 UTF-8 conservative units; 1–32768 |
| TRACE_OOMP_MAX_RESULTS | 5; 1–20 |
| TRACE_OOMP_TIMEOUT_SECONDS | 5; 0.1–15 |
| TRACE_OOMP_NUM_CTX | 8192 |
| TRACE_OOMP_GENERATION_RESERVE | 512; at least 256 |
| TRACE_OOMP_MAX_PROMPT_BYTES | 7000; 1024–32768 |
| Adapter response limit | 1 MiB streamed, 512 KiB structured output |
| Concurrent MCP calls | 4 |

The prompt byte cap plus generation reserve plus 256 units of safety overhead must fit configured num_ctx. Enabled generation retains /api/generate, llama3, temperature and num_predict, adding the configured num_ctx option. Bytes are a conservative accounting proxy, not an exact LLaMA tokenizer measurement.

The original recent transcript is kept complete. If it alone exceeds the enabled prompt cap, TRACE returns 413 before retrieval/generation instead of silently cutting source text or letting OOMP fallback bypass the cap. Whole historical memories that do not fit are omitted; proof/text is never partially clipped. Query messages over OOMP's 4096-character bound fall back with query_limit while TRACE's original 5000-character API bound remains unchanged.

Failures return the original latest-eight prompt with no fabricated memory. Invalid credentials, unavailable service, timeout, invalid response and rejected scope have distinct sanitized codes. The public successful chat response schema is unchanged. Per-interaction oomp_diagnostics contains only success/attempt flags, latency, selected evidence count, returned packet byte cost, final prompt bytes, degradation and error code. Packet bytes may exceed the subset ultimately selected for the prompt; both measures are deliberately separate.

response_time_seconds retains its original prompt-assembly-plus-generation interval. Enabled retrieval is now part of that interval. Delivery happens in a separate process and does not redefine Phase 3 accuracy/feedback metrics.

## Trusted publication and the MongoDB outbox

Only retrieve_and_ingest and a verified owner can stage new publication consent. A successfully persisted response receives the completion marker only after existing session bookkeeping succeeds. Generation/save/bookkeeping failures are ineligible for reconciliation. MongoDB remains authoritative for messages, IDs, timestamps, sessions and feedback.

Each chat has a small embedded oomp_publication object containing policy/consent, completion, exclusion and per-role delivery state. It references the actual MongoDB _id without duplicating message bodies. Event IDs/idempotency keys are deterministic SHA-256 encodings of owner ID, persisted interaction ID and role, within OOMP's actual 128-character Identifier constraints.

User statements use user_message/user grants; assistant output uses assistant_message/assistant grants; completed feedback uses feedback/user attribution. External source IDs are the actual Mongo interaction IDs. Session IDs use a documented safe hash encoding, turn IDs preserve source role, timestamps come from persisted BSON values, and arbitrary locator fetching is absent.

Writer descriptors are trusted deployment configuration, not model parameters. A separate host-only HMAC key signs the exact documented Stage 7 approval envelope, including grant identity/source policy, exact payload, nonce and short expiry. The signing implementation is a wire-format client, not an import or copy of OOMP storage/domain services. Real OOMP tests accepted user, assistant and feedback signatures, rejected tampering and retained assistant attribution.

Delivery states are pending, delivering with a 30-second lease/fence token, retry, delivered, failed or excluded. Claims/acks are atomic conditional updates in the original Mongo document. At most five automatic attempts use bounded exponential backoff. Permanent authorization/conflict/policy failures stop immediately. Lost acknowledgements leave a recoverable lease; replay resends the same source identity and OOMP's Stage 2 idempotency prevents duplicate events. An exhausted uncertain lease is marked failed, never silently stuck or falsely delivered.

This is at-least-once delivery, not a distributed transaction between MongoDB and SQLite. A crash after the completion marker but before outbox entries is repaired by reconciliation. A crash before a durable successful completion marker is ambiguous and deliberately not automatically promoted. A network error can leave a committed write unacknowledged; the persisted authoritative marker determines subsequent eligibility. MongoDB distributed transactions are not required.

Run explicit delivery separately:

~~~powershell
.\.venv\Scripts\python.exe -m backend.services.oomp_diagnostics status
.\.venv\Scripts\python.exe -m backend.services.oomp_diagnostics reconcile --owner "<pinned-owner-id>" --limit 20
.\.venv\Scripts\python.exe -m backend.services.oomp_diagnostics work --owner "<pinned-owner-id>" --limit 20 --poll-seconds 2 --approve
~~~

Reconcile defaults to dry run. work requires explicit --approve, repairs only already-consented successful gaps, drains due entries, and stops on Ctrl+C. Use --cycles 1 for one bounded pass, or drain --approve for one delivery-only batch. Each invocation checks the explicit configured owner; changing --owner cannot select another grant.

Feedback scheduling happens after the original submit-once database update. Scheduling failure cannot undo or block valid feedback; later reconciliation repairs a missing feedback entry. No feedback event exists before submission. Finalization and all analytics calculations remain the existing Phase 3 implementations.

## Explicit legacy backfill and exclusion

No startup or reconciliation scan automatically consents legacy history. Dry run first:

~~~powershell
.\.venv\Scripts\python.exe -m backend.services.oomp_diagnostics backfill --owner "<pinned-owner-id>" --limit 20
~~~

Review counts, invalid records and next_after_id. Only then add --approve. Continue with --after-id when paging. Batches are capped at 100; IDs/roles remain stable. Missing source timestamps/invalid records are reported, other users ignored, and failed staged records are not promoted as legacy completions.

Before delivery, an owner administrator can persist a no-publication marker:

~~~powershell
.\.venv\Scripts\python.exe -m backend.services.oomp_diagnostics exclude --owner "<pinned-owner-id>" --interaction-id "<mongo-id>" --approve
~~~

Excluded records cannot be reconsented by backfill or reconciliation, and their evidence is rejected in prompt validation. Exclusion is not remote erasure and cannot recall already accepted/in-flight events. OOMP's privileged erasure/conflict approval remain external local administration, never model tools.

## Reproduce the synthetic demonstrations (historical Stage 8)

~~~powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests\test_oomp_end_to_end.py -v
.\.venv\Scripts\python.exe -m pytest -v
~~~

Tests launch the independent external OOMP executable with -B, create temporary synthetic server data/configuration under ignored TRACE test artifacts, connect through actual TCP/MCP, and clean up listeners. Set TRACE_TEST_OOMP_PYTHON if its executable differs. No OOMP source module is imported into TRACE and no real conversation is backfilled.

The central test captures actual baseline and memory-enabled prompts in data/stage8-artifacts/long-history-demo.json. It proves the early project fact is absent from latest-eight context and present with original provenance after MCP retrieval, while all eight recent turns remain. Its model response is mocked; it does not claim a baseline model must answer incorrectly. Separate live llama3 smoke results are recorded in validation.

See [official SDK client transports](https://py.sdk.modelcontextprotocol.io/client/transports/) for upstream context; the authoritative local Stage 7 contract is the separately installed OOMP documentation. No desktop-host, public OAuth, multi-user or answer-accuracy certification is implied.
## P4B explicit context.v1 selection

P4B adds the trusted server setting `TRACE_OOMP_RETRIEVAL_API`:

| Value | Behavior |
| --- | --- |
| `retrieve` (default) | Existing `memory.retrieve` path, latest-eight prompt, legacy fallback and size behavior. |
| `context_v1` | Opt in to `memory.context` with strict `oomp.context.v1` parsing, independent Mongo proof validation and finite adaptive allocation. |

The selector does not enable memory. `TRACE_OOMP_MODE=off` remains the original prompt/model path and ignores optional integration settings. The two existing enabled modes retain their meanings: `retrieve` reads only; `retrieve_and_ingest` additionally stages consented successful new interactions through the existing outbox. Selecting context changes neither the publisher policy identity nor signatures, source roles, consent, event IDs, retries, leases or fences. It does not start a worker or publish data during retrieval.

An administrator opts in only through the trusted TRACE server environment after provisioning the existing owner pin, loopback settings and dedicated read grant. HTTP request fields cannot select an API, grant, tenant, namespace, principal, source ID or arbitrary recent-user hint. Unknown enabled selector values fail configuration validation. Old deployments are never upgraded automatically.

The client discovers `memory.context` through the existing authenticated MCP lifecycle and validates its advertised schema. It then independently checks the exact version, allowed fields and types, finite scores, counters, status/coverage, matching proof identities, packet/outer equality and UTF-8 byte accounting. Returned `token_budget` must equal the actual per-call request and returned evidence count must fit `max_results`. Duplicate JSON packet keys, malformed or duplicate proofs and mismatched source-reference order are rejected. Reason codes are bounded identifiers; they do not establish authority. Degraded results require the existing explicit `TRACE_OOMP_ALLOW_DEGRADED` policy.

No legacy downgrade or alternate credential is attempted when context is disabled, unavailable, unsupported or denied. The request omits `include_source_content`, uses `graph_depth=0` and `explain=false`, and accepts neither a `source_evidence` result nor unsolicited raw proof quotes or a query plan. The adapter does not upgrade its read credential to `read_source`. Any separately requested raw-source detail would require a real server grant and is outside this adapter. Authorized original conversation text is reconstructed from MongoDB instead of trusting a remote raw-source claim.

## P4B source authority and temporal limits

MongoDB remains the authority for TRACE interactions and sessions. Before rendering every historical proof, TRACE verifies the authenticated pinned owner, canonical Mongo ObjectId, an original interaction under that owner, an owner-linked session, configured `trace-ai` source system, deterministic role-specific event and turn identities, session hash, exact timestamp and absent locator. It rejects missing, foreign, unlinked or excluded sources. Naive BSON UTC timestamps are normalized to aware UTC in temporary views without rewriting stored records. Spans use Python Unicode code points, never UTF-16 positions or UTF-8 byte offsets.

The source validator checks original role content: user message, assistant response, or the exact existing sorted compact feedback serialization. Submitted feedback keeps its original attribution and timing. Feedback evaluates an assistant answer; it does not independently verify a user's factual claim.

Only complete original role source content is rendered in the prompt, with source interaction/event/memory IDs, source reference, validated span, role and uncertainty. An apparently correct substring can omit surrounding negation; rendering the full source preserves that context. Arbitrary OOMP `content` paraphrases, object labels, similarity scores and model answers are never promoted to independently verified facts or rendered as factual authority. Duplicate complete sources can be accounted for without discarding distinct conflicting source content or uncertainty annotations.

A retracted unit is rejected. A superseded unit is accepted only for explicit `historical_correction` retrieval and remains labeled historical, never current-state authority. Tentative, contradicted, corrected and uncertain material retains its supplied temporal/assertion metadata. Exact source linkage proves attribution and span integrity, not semantic entailment, complete correction coverage or external truth. An unseen correction can still be absent from a remote result. The prompt instructs the answer model to preserve negation, chronology, quoted/hypothetical origin and role; it does not certify the model's compliance. Project names do not establish aliases; robot discussion does not establish pet ownership; political topics do not establish affiliation, nationality, ethnicity or beliefs.

## P4B adaptive allocation and fallback

Context mode keeps the original session lifecycle lock, active-session ownership and pending-feedback checks before retrieval or generation. It loads at most 32 owner/session-scoped complete exchanges, excluding publication-excluded records. If that bounded scan omits older rows, the count outside the window is reported as unknown. Omission counters explicitly apply to the loaded window.

The allocator first reserves fixed instructions, the complete current user message, and the latest complete exchange with its submitted feedback. It reserves an evidence share before adding a deterministic newest suffix of whole older exchanges. Where useful and affordable, it may include at most two complete original user turns from omitted exchanges selected by finite exact query-term overlap. These are labeled older extractive source views, with original IDs, timestamp and full span, omitted assistant-response attribution and feedback target. They are not generated summaries or proofs of semantic relevance.

At most two complete recent-user hints, totaling at most 2048 UTF-8 bytes, come from the loaded authorized current session. Assistant answers, feedback, client-supplied IDs and cross-session identifiers are not hints. Oversized whole hints are omitted, never clipped.

There are three separate capacity measures:

| Measure | Meaning |
| --- | --- |
| OOMP `token_budget` / returned packet bytes | UTF-8 bytes of the complete serialized context packet only. The per-call budget may be below the configured evidence maximum. |
| TRACE final prompt bytes | Actual UTF-8 length of instructions, current message, complete recent context, selected full historical sources, JSON escaping, labels and separators. |
| TRACE `prompt_token_upper_bound` | Conservative one-byte-per-token accounting proxy. It is not a tokenizer measurement or a tested model-context capability. |

TRACE remeasures each whole provenance-validated source unit after rendering. A small remote packet may reference a large authoritative Mongo source; the full source can therefore be excluded even when its transport packet fits. Text and proof stay together. The final prompt must satisfy both the configured byte cap and `prompt_token_upper_bound + generation_reserve + 256 <= num_ctx`. Existing defaults remain 7000 prompt bytes, 8192 context allowance and 512 generation reserve; enabled model generation retains `num_predict=140`. Increasing a configured allowance does not demonstrate that hardware or a model can support it.

Whole discretionary units/exchanges are omitted deterministically and exclusions are reported. A long session can proceed with fewer complete exchanges under this opt-in policy. If the complete mandatory minimum cannot fit, TRACE returns HTTP 413 before retrieval or generation. The current message and factual assertions are never byte-truncated. The public 5000-character request bound remains unchanged; oversized public input can fail request validation with HTTP 422 before reaching allocation. Existing legacy latest-eight 413 behavior is unchanged.

| Context outcome | Meaning presented to the answer model |
| --- | --- |
| `found_relevant_evidence` | Source-validated historical evidence was selected. Its contents remain attributed source statements. |
| `no_relevant_evidence` | This query returned no relevant evidence; it does not establish absence of past conversation. |
| `budget_excluded` | Relevant evidence or additional context could not fit as complete units. |
| `index_incomplete` / `coverage_unknown` | Coverage is partial or unknown; no exhaustive-history claim is justified. |
| `candidate_uncertain` | Evidence is uncertain or potentially conflicting and requires cautious attribution. |
| `context_disabled` / `context_unsupported` | The remote tool is unavailable by configuration or capability/version support. |
| `unavailable` / `timeout` | Retrieval failed or exceeded its deadline; historical absence is unproven. |
| `unauthorized` | Access was denied; no alternate or broader grant is attempted. |
| `invalid_evidence` / `source_validation_unavailable` | Wire/provenance validation failed or authoritative source validation could not complete. |

Malformed status/evidence combinations fail closed. Retrieval failure uses a bounded current/recent-context prompt with truthful status and no remote historical content. It does not restore an oversized latest-eight prompt or say that no earlier conversation exists. If the mandatory recent-source view itself cannot be validated, TRACE fails the request rather than consuming unverified rows.

Diagnostics record finite API/status/count/byte/timing values, coverage, loaded-window exclusions, compaction/deduplication counts and sanitized failure codes. They omit raw prompts, source text, query text and credentials. Retrieval time, pre-generation orchestration time and complete chat time have distinct meanings. The successful public chat schema, original OAuth flow and feedback contracts remain unchanged.

## P4B offline validation scope

The fictional three-session fixture freezes source rows, gold evidence, workloads and 33 negative controls before implementation tuning. A separately preserved amendment corrects the prose denominator from 17 to the actual 16 source-case gold pairs without changing inputs or gold. The mocked MCP selections test adapter retention and rejection, not actual OOMP ranking. Complete original sources are independently checked against mongomock records. Actual chat persistence, feedback and outbox behavior use only disposable fictional storage and deterministic fake responses.

Source recall/precision, continuity and temporal-correction measures describe evidence present in the final prompt. The conservative fake answer explicitly declines personal assertions, so its abstention and false-assertion counts do not certify natural-language reasoning. UTF-8 bytes and the byte-based token proxy do not measure the LLaMA tokenizer. Mocked retrieval/orchestration latency does not measure actual service or inference speed. Exact results, failures, skips, resource evidence and remaining limitations belong in the P4B report.

The reviewed experimental controller supplies offline access guards, synthetic environment, resource monitoring, cancellation and owned-process cleanup. Those are validation-harness controls, not newly shipped TRACE runtime protection. Existing Windows crash evidence remains historical; these tests cannot establish that a BSOD cause was resolved.

A later real LLaMA evaluation requires separate owner authorization, a fresh resource preflight, fixed workload and approved live-service boundaries. It is not part of the offline quickstart. The roadmap's second independent MCP host example also remains required before final P4 acceptance; the TRACE adapter alone does not complete that requirement. No P5, release or deployment approval follows from this local milestone.