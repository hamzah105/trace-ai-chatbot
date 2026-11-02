# P4B TRACE implementation plan

2 November 2026, Asia/Karachi. Local-only authorized work; no commit, push, deployment, release, live model inference or P5.

## Verified baseline and boundaries

TRACE clean main and remote main: af202ef43daf70280d2e8915210816f788e8aff1. Working branch: feature/p4b-adaptive-context.
OOMP accepted main: d34bfbbbec44b0e016ddc41da1a7e27a45d45a68. PR #4 is merged; post-merge run 41347026380 passed all five jobs. All 95 runtime files in the accepted installed P4A validation environment still match its installation certificate; context.v1 and MCP wiring are present. Operator profiles/services were not inspected or enabled.
The complete five-milestone roadmap was read (SHA256 70c8150e167c44fe1475957c0feb9e1d814f7d0ba33db0f679bb9ba1b517cc59). Historical schema-v5/no-extractor descriptions are dated baseline statements, not the current P4A implementation.

OOMP runtime, existing databases, private TRACE MongoDB, credentials, saved conversations, OAuth, publisher signatures/consent, and prior artifacts remain unchanged. Only TRACE public source/docs/tests and fresh ignored data/p4b-* validation artifacts are in scope.

## Architecture

1. Add an explicit server-owned retrieval API selector, default legacy. Only context_v1 opts into memory.context; existing off/retrieve/retrieve_and_ingest meanings and legacy byte output remain compatible. Do not change publication policy_id identities.
2. Mirror the strict oomp.context.v1 wire contract independently in TRACE. Discover/validate memory.context via the existing MCP lifecycle. Match the actual per-call evidence budget and max-results; preserve identity, transport/auth, timeout, concurrency, response-size and log-redaction boundaries. Missing capability must not cause a silent legacy or wider-scope query.
3. Reconstruct each original role source from authenticated owner-scoped Mongo interactions and sessions. Validate configured source system, deterministic event/session/turn IDs, timestamps, absent locator, exclusion policy, Unicode-code-point spans and any supplied exact quote. No object label, similarity score, model answer or returned scope field establishes authority.
4. Preserve derived/assertion/temporal uncertainty. TRACE can verify its authoritative source spans and attribution, but cannot independently certify an arbitrary OOMP paraphrase or internal summary manifest using wire links alone. Render complete original role source content with derived/uncertain metadata; do not render arbitrary wire paraphrases or object labels as authority. Document the semantic validation limit.
5. Add a separate structured recent-history loader for context mode. Load bounded owner/session-filtered complete exchanges; retain current message, mandatory instructions and latest complete exchange with its submitted feedback. Keep a deterministic suffix, disclose whole exclusions, and optionally include complete extractive older user-source views with IDs only when independently authorized and useful. Never invent a summary, split a claim or remove negation.
6. Allocate a finite full prompt and evidence share. Count actual serialized UTF-8 prompt and formatting overhead; separately report transport estimates and a conservative byte-based model-token upper-bound proxy. Enforce prompt cap and prompt estimate + generation reserve + safety <= configured context allowance. Preserve the existing num_predict=140 behavior and 512 default output reserve; neither is a tokenizer measurement.
7. Derive at most two complete recent user hints, <=2048 UTF-8 bytes total, from the authorized loaded rows. No client-supplied scope/IDs or assistant/feedback text becomes a user hint.
8. Use truthful found/empty/budget/incomplete/uncertain/unavailable/unsupported/timeout/unauthorized outcomes. A failed or empty retrieval cannot assert that no prior conversation exists. A bounded fallback retains current request and required recent/feedback material without broadening authority.
9. Keep route session locks, ownership, pending-feedback gate, final persistence, publisher and outbox idempotency unchanged. Diagnostics are finite counts/status/bytes/timing, never raw prompt, source text or credentials.

Likely files: backend/services/{oomp_config,oomp_client,oomp_contracts,oomp_context,chat_orchestrator,oomp_diagnostics}.py, backend/routes/chat.py, separate allocation/provenance helpers as justified, tests/test_p4b_*.py, versioned fictional fixtures/evaluation, docs and a fictional quickstart. ollama_service.py changes only if a concrete output-reserve incompatibility requires a narrowly tested correction.

## Security and acceptance matrix

| Boundary | Required synthetic controls |
| --- | --- |
| Opt-in/compatibility | Off and legacy exact behavior; both enabled modes; unknown selector; missing tool/version; no implicit downgrade or SDK requirement in off mode |
| Trusted identity | Foreign owner/session/tenant/principal claims; forged source system/event/turn/timestamp/locator; missing/deleted/excluded source |
| Exact proofs | Wrong/reversed/out-of-range spans, Unicode emoji/combining/Urdu/CJK, wrong quote, duplicates, unknown fields, packet/outer mismatch |
| Source semantics | Alias versus project names; tentative plan/correction versus completed move; political topic versus affiliation; assistant/quoted/hypothetical origin |
| Prompt/budget | Identical old/new long-eight 413 inputs; full current message; newest complete exchange and feedback; whole-unit proof omission; UTF-8/JSON overhead; impossible mandatory minimum |
| Memory states | Found, no relevant evidence, budget excluded, incomplete/unknown coverage, uncertain/conflict, unavailable, unauthorized, unsupported and timeout |
| Workflow | Session-ended/pending-feedback/owner failures before MCP/model; no duplicate ingest/outbox writes; existing OAuth/publication rules |
| Resource/privacy | Fresh short disposable storage, no dotenv/private profile reads, no real Mongo/Ollama/cloud/model downloads, sequential tests, owned-process cancellation and RAM/commit polling |

Freeze independently authored source/gold/negative controls and metric denominators before implementation tuning. Initial adapter gates: zero unauthorized prompt sources, invalid accepted proofs, packet/prompt overflows, fabricated completed moves/affiliations, duplicate publication writes or unreported exclusions; all designated negative controls abstain. Report source recall/precision against supplied frozen synthetic MCP fixtures separately from real OOMP retrieval or real answer quality. Fake-answer assertions validate orchestration only.

## Validation order and stop gate

Review test dependencies and existing fixtures before execution. Use a new isolated Python test environment with fresh offline guards; do not execute an old acceptance environment's startup hook or mutate its ledger. Suppress dotenv; use only mongomock and mocked MCP/fake model. Existing external OOMP-service cases must not launch their default installed Python, server or worker; record any boundary-driven omissions explicitly and cover the new adapter through isolated synthetic protocol tests.

Run baseline first, then focused contract/provenance/allocation/security tests, then complete applicable regressions sequentially. Preserve every failure, command, source snapshot, JUnit and resource record. Stop on instability, uncertain ownership, stale/failed resource or cancellation monitoring, <1.5 GiB RAM, >=85% commit, or attempted real inference. Offline admission requires >=4 GiB RAM and <75% commit. No automatic retry of a failed suite; diagnose and use a new result directory.

Complete docs/product-milestone-P4B-report.md with actual results and reproduction commands. Document deployment requirements, no tokenization/real-model quality claim, and the still-required second independent MCP host example before final P4 acceptance. Successful local work ends with “P4 Phase B ready for owner review.”
