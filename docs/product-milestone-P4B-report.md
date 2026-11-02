# P4B: TRACE adaptive context allocation and cross-session integration

2 November 2026 (Asia/Karachi). Local offline implementation is ready for owner review. No commit, push, merge, deployment, release, live inference or P5 work was performed.

## Accepted baselines

- TRACE local and GitHub main: `af202ef43daf70280d2e8915210816f788e8aff1`. Local branch: `feature/p4b-adaptive-context`; its HEAD remains that baseline, with the changes below uncommitted and unstaged.
- OOMP main: `d34bfbbbec44b0e016ddc41da1a7e27a45d45a68`, integrating P4A `cf70fc7f3aa872605b9af81785166f53624d832a` through [PR #4](https://github.com/hamzah105/OOMP/pull/4). The actual post-merge [run 41347026380](https://github.com/hamzah105/OOMP/actions/runs/41347026380) was rechecked: Windows 3.11/3.12, Ubuntu 3.11/3.12 and archive build/clean-install all succeeded.
- The accepted installed P4A validation environment exposes the context contract and MCP service. Its 95 runtime module hashes matched the preserved installation certificate. TRACE imports no OOMP implementation; no OOMP runtime, database, profile or provider was executed or modified.
- The complete five-milestone roadmap was reviewed; SHA256 `70c8150e167c44fe1475957c0feb9e1d814f7d0ba33db0f679bb9ba1b517cc59`. Roadmap proposals did not independently authorize later work.

## Implemented behavior and trust boundaries

`TRACE_OOMP_RETRIEVAL_API=context_v1` explicitly selects the new adapter while `TRACE_OOMP_MODE` retains its existing off/retrieve/retrieve_and_ingest meanings. Default selector `retrieve` keeps the old latest-eight path. Off mode ignores optional integration settings. The new branch executes only after verified-owner authentication; the unchanged chat route retains session ownership/status, lifecycle locking and pending-feedback checks first.

The client discovers `memory.context`, checks its schemas and independently validates `oomp.context.v1`, complete packet/outer equality, UTF-8 byte accounting, per-call budget, counts, strict types, source references and bounded reason/trace identifiers. Missing capability, disabled tool, unsupported version, timeout, authorization and unavailability have separate sanitized outcomes. No legacy downgrade or alternate grant is attempted. Existing loopback-only transport, credentials, response limits, concurrency limit and cancellation behavior remain in place. Diagnostics distinguish discovered tool availability from the expected contract; a tool name alone is not reported as negotiated version support.

The request never asks for raw source content or a query plan. Unsolicited source_evidence/quotes are rejected rather than implicitly upgrading the read grant to read_source. Owner-authorized original content comes from Mongo-shaped host records. Every proof must match canonical Mongo ObjectId, current owner and owner-linked session, configured source system, deterministic event/session/role-specific turn identity, exact UTC timestamp, absent locator and exact Unicode-code-point span. Excluded or malformed publication metadata is rejected. Missing/None legacy publication metadata remains compatible. Naive BSON UTC timestamps are normalized in temporary views without rewriting records.

The prompt renders complete original user/assistant/feedback role content with IDs, proofs and uncertainty. It never renders arbitrary wire paraphrases or object labels as factual authority; a linked substring alone cannot prove an invented claim or remove surrounding negation. Retracted units and superseded current-use units fail closed; historical supersession remains explicitly historical. Contradiction, tentative status, corrections, source role and chronology remain visible. These checks establish source attribution and exact spans, not external truth or completeness of unseen corrections.

The allocator loads a bounded 32-row authorized current-session window, reserves fixed instructions/current message/latest complete exchange and feedback, reserves evidence capacity, then adds a deterministic suffix of complete exchanges. Up to two relevant complete older user-source views can be included extractively with attribution and omitted-assistant/feedback labels. These are not invented summaries. Up to two complete current-session user hints, totaling at most 2048 UTF-8 bytes, come only from authorized loaded rows. Client-supplied IDs, other owners, other sessions, assistants and feedback cannot supply hints.

All formatting, JSON escaping, selected complete sources and final prompt bytes are measured. Final prompt bytes must fit the configured cap and the byte-based token proxy plus generation reserve plus 256 safety units must fit num_ctx. Existing defaults remain 7000/8192/512 and actual model num_predict remains 140. Bytes are a conservative proxy, not measured tokenizer output. Whole units are omitted and counted; current instructions and assertions are never byte-truncated. A genuinely impossible mandatory minimum still returns 413 before retrieval or generation.

Found, empty, budget-excluded, incomplete/unknown coverage, uncertain, disabled, unsupported, denied, unavailable and timed-out results remain distinct. Failure fallback retains bounded current/recent sources with truthful status, rather than claiming that no previous conversation exists or restoring an oversized prompt. Retrieval introduces no automatic consent, outbox delivery or ingestion-policy change. Publisher signatures, policy_id, source IDs, consent, feedback attribution and lease/fencing implementation remain unchanged.

## Exact changed files

Modified existing files:

```text
backend/services/chat_orchestrator.py
backend/services/oomp_client.py
backend/services/oomp_config.py
backend/services/oomp_diagnostics.py
docs/oomp-integration.md
```

New runtime files:

```text
backend/services/oomp_adaptive_context.py
backend/services/oomp_allocator.py
backend/services/oomp_context_contracts.py
backend/services/oomp_context_provenance.py
```

New test and fixture files:

```text
tests/p4b_evaluation.py
tests/p4b_support.py
tests/test_p4b_allocator.py
tests/test_p4b_diagnostics.py
tests/test_p4b_environment.py
tests/test_p4b_evaluation.py
tests/test_p4b_orchestration.py
tests/test_p4b_protocol.py
tests/fixtures/p4b/v1/amendment-01-metric-arithmetic.json
tests/fixtures/p4b/v1/gold.json
tests/fixtures/p4b/v1/manifest.json
tests/fixtures/p4b/v1/negative-controls.json
tests/fixtures/p4b/v1/preregistration.md
tests/fixtures/p4b/v1/scenarios.json
tests/fixtures/p4b/v1/sources.json
tests/fixtures/p4b/v1/workloads.json
```

New documentation: `docs/P4B-implementation-plan.md`, `docs/oomp-p4b-fictional-quickstart.md`, and this report. Total public change inventory: 28 files. No routes, OAuth, database configuration, publisher, security module, model service, frontend or requirements file changed.

## Frozen synthetic evaluation

The independently authored v1 fixture froze at 2026-11-01T21:01:48Z, before result-driven implementation tuning. Manifest SHA256: `964b23803a06c9f3455010eda3a965299a2e624bc0a0eee088a074516f682b9e`. Original prose said 17 source-case pairs; the separately preserved amendment corrects the arithmetic to the actual 16 without changing source/gold/scenario inputs. Amendment SHA256: `054e351401f90cef73e53459903a5d70900e32faedff48540c144db6146d7c07`.

All data are fictional: ORBIT42, explicit alias NOVA, robot KESTREL, response preference, tentative relocation and cancellation, proposed infrastructure, unrelated political discussion, quoted/hypothetical material, Unicode and foreign-owner controls. Actual chat orchestration and synthetic persistence execute with mongomock, mocked MCP and a deterministic JSON answer stub. The stub lists received source IDs and declines personal assertions; it does not generate gold answers.

| Measure | Actual result | Interpretation |
| --- | --- | --- |
| Micro source recall | 16/16 | Retention of supplied gold MCP sources; not OOMP ranking recall |
| Macro source recall | 10/10 nonempty cases, mean 1.0 | Twelve scenarios total; empty-gold cases remain in security/abstention |
| Source precision | 16/16 included source-case pairs | Relevant authorized originals in final prompts |
| Prompt proof integrity | 16/16 included sources | Original role/text/span/identity independently checked |
| Cross-session continuity | 5/5 required claim-source groups retained | Evidence continuity, not real-model answer accuracy |
| Corrected relocation | 1/1 episode with both proposal and correction | Complete original sources and uncertainty preserved |
| Foreign source injection | 2/2 rejected; 0 foreign sources included | Two frozen scenario injections; additional negative controls also passed |
| Personal abstention | 4/4 designated cases; 0 new assertions | Conservative fake-stub behavior only |
| Negative controls | 33/33 executed and passed | Wire/source rejection or preserved role/uncertainty for semantic controls |
| Publication idempotency | 3 mock accepted role deliveries, 3 unique event IDs, 3 stored role states | User, assistant and submitted feedback; repeated claims rejected; 0 duplicate accepted writes, 0 retries |

No completed move, personal political affiliation, alias-from-project, or pet-from-robot/hypothetical claim is introduced as prompt authority. The fake-stub result cannot establish that a future language model will reason correctly.

## Prompt budget and failure results

| Identical frozen long-eight workload | Legacy | Opt-in context |
| --- | --- | --- |
| Outcome | HTTP 413 | HTTP 200 with fake answer |
| Full prompt bytes | 108098 | 20920 |
| Complete recent exchanges selected | Fixed eight cannot fit | 2 retained, 6 explicitly excluded |
| Historical source units | Retrieval blocked by old size guard | 3 included |
| HTTP 413 frequency for this matched request | 1/1 | 0/1 |

Both modes use exactly the same input rows and current message. The old byte count is captured before the new route persists its additional exchange. Frozen settings: prompt cap 32768 bytes, num_ctx accounting allowance 65536, packet budget 6144 bytes, generation reserve 512, safety reserve 256, num_predict 140. The new prompt plus reserves is 21688 units. These configuration values do not demonstrate model/hardware capacity. A separate matched default-cap route regression also proves old 413/new success under 7000 bytes with latest complete exchange and submitted feedback preserved.

A 9019-code-point historical source with a 936-byte wire packet is excluded whole under a 7000-byte prompt cap; final prompt 2624 bytes, status budget_excluded, excluded_units=1. A valid 3000-CJK-character public request returns 413 before any MCP/model call. The frozen 88000-character request instead meets the unchanged 5000-character schema guard first (422); the frozen 256-byte cap fails configuration admission, with the pure allocator minimum checked separately. No guard was weakened to convert those into an artificial 413 demonstration.

Across the 12 frozen scenarios, prompts were 2598-8160 bytes. Mocked retrieval latency was 1.813-4.094 ms; internal pre-generation orchestration 2.235-4.996 ms; full fake chat route 3.497-32.161 ms (including the first case's cold path). The matched long-eight route took 9.419 ms, with 2.774 ms mocked retrieval. Individual timings and byte counts remain in the JSON/JUnit evidence. These measurements do not characterize actual MCP service speed or inference performance.

## Sequential regression evidence

Actual runtime: stock Python 3.11.4 on Windows, fresh qa311 interpreter without pip/site startup; reviewed existing TRACE dependencies added as plain read-only import paths. Installed optional SDK is MCP 2.3.0; Node 24.14.1 covers existing frontend checks. No package/model downloads or system changes were made. Python 3.12 and other operating systems were not rerun for TRACE P4B and are not certified by these results.

Primary successful controller root: `data/p4b-20261102T0347236933832Z/`.

| Phase | Passed tests | Skipped | Deliberately deselected | Additional unittest subcases |
| --- | ---: | ---: | ---: | ---: |
| Frontend guard verification | 8 | 0 | 0 | 0 |
| Baseline before runtime overlay | 208 | 8 | 1 | 55 |
| Protocol and allocator | 89 | 0 | 0 | 0 |
| Route orchestration and diagnostics | 63 | 0 | 0 | 0 |
| Frozen evaluation | 38 | 0 | 0 | 0 |
| Complete applicable final regression | **398** | **8** | **1** | **55** |

Focused and full counts overlap; do not add them. The baseline includes the one new dependency-import probe while runtime code was still unchanged. Final regression collected 407 top-level tests, deselected one, and completed 406 (398 passed, 8 skipped). Pytest/JUnit additionally records 55 unittest subcases: JUnit therefore has 461 testcases, zero failures/errors, eight skips. The artifact audit's call-report count includes these subcases; it is not the top-level count. Final console time 13.48 s; bounded controller wall time 16.862 s. All watched source hashes stayed unchanged during every successful phase and still match final runtime files.

The eight existing external-OOMP cases deliberately skip through a nonexistent executable sentinel: invalid credentials, discovery/status, old long-history integration, foreign-scope wire, independent sync lifecycles, owner-linked recall, role/idempotency/approval tampering, and outage/replay. The physical-Mongo test `tests/test_oomp_publisher.py::test_real_mongo_outbox_survives_client_reopen_and_replay` is deselected before execution because it connects to port27017 and writes a physical database. Exact node IDs/reasons are preserved in test-accounting.json. These are explicit validation limits, not passing live tests.

Final run warnings: one existing Starlette multipart deprecation and 38 pytest warnings about record_property with xunit2. JSON reports remain the primary detailed metric artifacts; the warnings did not fail tests and were not hidden. The optional dependency set is unchanged; normal development requires requirements-dev.txt, enabled deployment requires requirements-oomp.txt and existing trusted owner/grant configuration. Single application worker and independent local OOMP process boundaries remain necessary.

## Preserved failures and Windows safety

All 11 timestamped controller roots and 20 phase results under data/p4b-* are retained, including latched stop flags, stdout/stderr, JUnit where produced, source snapshots and ownership/resource records. No previous ledger was reset or deleted. Comparing every available before/after source snapshot found zero source mutations, including interrupted phases; an early result's source_unchanged=false means its success bookkeeping did not complete, not a detected source edit.

The resumed baseline exposed artifact-harness compatibility issues before product validation: Windows NUL spelling; replacing subprocess.Popen with a function despite asyncio subclassing it; Windows command-line-string audit tickets; pytest compiler synthetic filenames and JUnit hostname shell lookup; omitted PyWin32 plain import paths under no-site startup; truststore's platform metadata shell fallback; extended local-drive spelling during pytest temporary-directory cleanup; and getter-only Node24 exports. Each failure was preserved and diagnosed before a fresh result/controller. The complete intermediate baseline `data/p4b-20261102T0343098331981Z/baseline-311/` remains **202 passed, 6 failed, 8 skipped, 1 deselected, 55 subcases**; all six failures were the Node guard initializer. No TRACE security assertion or original test was weakened to pass.

Corrections remained in the experimental harness: compatible guarded Popen class with exact audit tickets, reviewed plain PyWin32 paths without old startup hooks, synthetic/native platform metadata without shell authorization, narrow diagnostic filename handling, exact extended local-drive canonicalization before ordinary containment checks, and descriptor-aware fail-closed Node protection. No prohibition on private files, real model/Mongo endpoints, external networking or unrelated executables was removed. Historical blocked operations were harness false positives/metadata operations, not real model or database requests.

The final suite's minimum available RAM was 6754779136 bytes (about 6.291 GiB), maximum system commit 33.8801%, and maximum monitor gap 0.5303 s. Admission required >=4 GiB RAM and <75% commit; continuous stops remained <1.5 GiB RAM, >=85% commit, cancellation, stale/failed monitoring, lost ownership or new instability. The final controller owns its child Windows Job and only terminates that job. These controls are experimental validation functionality, not newly shipped TRACE runtime protection.

The boot session remained unchanged and the fresh read-only System health review found no new critical/error event during this resumed work. The owner's earlier manual shutdown/restart remains classified as manual. Historical crash evidence remains intact; this work makes no claim that a BSOD cause was resolved.

## Final integrity, reproduction and remaining gates

OOMP is still clean at its accepted main SHA. TRACE's index is empty and HEAD unchanged. Git diff --check passes; existing Git line-ending warnings are informational, with no global configuration change or staging. The 28 public changes are limited to the source/docs/synthetic-test inventory above. Pattern scans and manual inventory review found no credential material, private database, model weights, crash dump, generated environment, experiment directory or unrelated source in public changes. All data/p4b-* evidence remains ignored. Private TRACE MongoDB, saved conversations, credentials, private OOMP profiles and Windows settings were neither accessed nor modified by the tests.

Use [the fictional offline quickstart](oomp-p4b-fictional-quickstart.md), not the historical Stage8 live-service commands. It uses a reviewed fresh controller, fresh phase names, mock MCP/answers and disposable storage. Local evidence is in the successful controller's per-phase result.json, command/spec/environment facts, JUnit, test-accounting.json, resource samples and source snapshots. Frozen metric JSON files are under evaluation-311/tmp and also attached as JUnit properties. The preserved final-audit-20261102T0353347932296Z.json records hashes and all 20 earlier results; its passed call-report counts include unittest subcases as explained above.

Remaining limitations: no actual OOMP context service round trip or durable physical Mongo reopen was run in this offline scope; no real-model answer quality, real-network latency, tokenizer consumption or hardware-context capacity has been measured. Remote grant mapping remains the server's scope authority because the contract does not attest tenant/principal fields. Full original sources can cost more prompt bytes than their wire packet and be excluded. Bounded history, conservative lexical compaction and remote correction coverage are not exhaustive semantic memory. The current profile remains a pinned single-owner loopback development deployment.

A later real LLaMA3 evaluation requires separate owner authorization, an explicit resource preflight, fixed workload and approved live-service boundaries. The roadmap's **second independent MCP host example remains required before final P4 acceptance**. Do not infer final P4 completion, P5, deployment or release authorization from this local P4B result.

P4 Phase B ready for owner review. Stop for owner approval; no commit/push is performed or implied.