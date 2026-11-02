# Fictional P4B adapter quickstart (offline)

This exercise runs TRACE's opt-in context adapter against frozen fictional sources, mongomock, mocked MCP and a deterministic fake answer. It opens no real MongoDB or OOMP profile, starts no service, and performs no model inference or download. It does not backfill existing conversations. Do not use the historical Stage 8 service-start or external-server test commands for this exercise.

## What it demonstrates

The fixture is `tests/fixtures/p4b/v1/`. Every person, place, party, project, source and owner is invented.

| Session | Source material |
| --- | --- |
| `p4b-session-0` | Software project ORBIT42, explicitly distinct from a personal alias. |
| `p4b-session-1` | Concise replies and three bullets when useful; tabletop robot KESTREL; explicitly claimed alias NOVA; tentative Cedar Bay/Larch Haven relocation, then cancellation; proposed infrastructure; unrelated political comparison; quoted hypothetical and Unicode controls. |
| `p4b-session-2` | A recent complete exchange followed by cross-session questions. |
| Foreign-owner control | MISO, COMET and a completed move belong to another fictional owner and must never enter the authorized prompt. |

The runner converts the frozen JSON rows to BSON-shaped mongomock records and public MCP wire packets. It calls the actual TRACE chat route with the answer function patched to a conservative JSON stub. The stub lists the source IDs it received and declines personal assertions. TRACE persists one synthetic interaction, preserves original records, applies feedback gating and keeps publication behavior tied to the existing configured mode.

The adapter validates the `oomp.context.v1` wire, verifies each original owner/session/role/span against Mongo-shaped records and renders complete original source text. A deliberately unsupported wire paraphrase must not become prompt authority. The correction case requires both the tentative proposal and cancellation sources; a topic does not establish political affiliation, a project name does not establish an alias, and a robot or hypothetical does not establish pet ownership.

## Prerequisites

Use the accepted local P4B source on TRACE's dedicated feature branch. Python 3.11+ and TRACE's existing `requirements-dev.txt`/optional MCP dependencies must already be available in the reviewed test environment. No dependency installation, service setup or credentials are needed by these commands. OOMP remains a separate product; the tests import no OOMP implementation.

Use a newly prepared, reviewed artifact controller under ignored `TRACE/data/p4b-*` with its fresh `qa311` interpreter and `run_phase.ps1`, `bootstrap.py`, `node_guard.cjs` and harness manifest. The controller must match the implementation report's verified guard source. Do not copy an old acceptance environment's startup hooks or reuse a controller with a cancellation/violation flag. This document deliberately provides placeholders rather than choosing an existing or private environment.

The controller sanitizes the environment and home/temp locations, suppresses `.env` loading, bypasses prior site startup hooks, blocks prohibited model imports/endpoints and real MongoDB, limits child processes to reviewed guarded forms, snapshots source, writes fresh JUnit/log/resource evidence, and stops on cancellation, uncertain ownership, monitoring failure or instability. The resource policy requires at least 4 GiB available RAM and less than 75% commit for admission, stopping below 1.5 GiB or at 85% commit. These controls belong to the experimental harness, not shipped TRACE runtime protection.

## Run a fresh focused offline phase

Fill in the path to the newly prepared and reviewed controller. Do not set any real TRACE/OOMP credentials or service URLs. The synthetic test helpers set their own server-owned configuration, including `TRACE_OOMP_RETRIEVAL_API=context_v1`; the user's saved environment is not the test source.

```powershell
Set-Location 'D:\Desktop\VU BS-CS\CS619\TRACE'
$qaRoot = '<absolute path to the reviewed fresh TRACE data/p4b-* controller>'
$phaseName = 'p4b-focused-' + [datetime]::UtcNow.ToString('yyyyMMdd-HHmmss')
$qaPython = Join-Path $qaRoot 'qa311\Scripts\python.exe'
$focusedTests = @(
  'tests\test_p4b_environment.py',
  'tests\test_p4b_diagnostics.py',
  'tests\test_p4b_protocol.py',
  'tests\test_p4b_allocator.py',
  'tests\test_p4b_orchestration.py',
  'tests\test_p4b_evaluation.py'
)
& (Join-Path $qaRoot 'run_phase.ps1') -Phase $phaseName `
  -Python $qaPython -Tests $focusedTests -DeadlineSeconds 2400
```

Run one phase at a time. If it fails, preserve its result directory, stop marker, stdout/stderr, source snapshots, JUnit and resource samples. Diagnose the exact failure before preparing another phase or corrected fresh controller; do not delete stop flags or automatically retry. Do not run bare unguarded pytest against the complete repository: historical external-service fixtures are intentionally outside this offline exercise.

The controller selects the synthetic tests, blocks external OOMP executable discovery with a nonexistent sentinel and prevents physical MongoDB access. Its baseline/full-suite policy separately records external-service skips and excludes the one physical-Mongo lifecycle test before execution. These omissions must remain visible in the final report.

## Inspect the evidence

Read the new phase's controller result, `stdout.txt`, `stderr.txt`, JUnit XML and source/resource snapshots. Test-owned JSON reports reside under the fresh pytest temporary directory and are also attached as JUnit properties. The evaluation writes:

- `p4b-frozen-scenarios.json`: 12 cases, source recall/precision, proof integrity, five continuity opportunities, corrected episode, injected foreign rejection, per-case prompt bytes and timings.
- `p4b-frozen-long-eight.json`: identical frozen legacy/opt-in inputs, old/new status, prompt bytes, retained and excluded complete exchanges, selected evidence and generation reserve.
- `p4b-control-<id>.json`: each of the 33 frozen negative controls and its proof-rejection or attribution/uncertainty outcome.
- `p4b-frozen-boundaries.json` and `p4b-frozen-whole-unit.json`: public admission limits, impossible mandatory context, Unicode/JSON accounting and whole-source budget exclusion.
- `p4b-publication-idempotency.json`: one completed fictional exchange, actual feedback submission, three role-specific mock deliveries, stable event identities and duplicate/retry accounting.

Do not treat the report names as proof of success. Require the actual test/controller conclusions and inspect exclusions. The immutable manifest is checked before evaluation. Its separate amendment corrects the original prose denominator 17 to the actual 16 gold source-case pairs, with all original inputs and labels unchanged.

The frozen long-eight workload uses 32768 prompt bytes, 65536 context-accounting allowance, 6144 packet bytes, 512 generation reserve, 256 safety reserve and unchanged `num_predict=140`. The old/new prompt comparison uses the same eight input rows before the opt-in route adds a new interaction. These settings exercise deterministic accounting; they do not establish model or hardware capacity.

Two frozen boundary inputs meet an earlier public guard: the 88000-character current message is rejected by the unchanged 5000-character request schema, producing 422 before allocation; the 256-byte cap is rejected by configuration validation. The pure allocator minimum is checked separately without weakening either guard. A separate valid 3000-CJK route test demonstrates an actual mandatory-context 413 before MCP or fake generation.

## Interpretation and remaining gates

Source recall/precision describes retention of supplied synthetic MCP selections, not actual OOMP retrieval ranking. Continuity and correction accuracy here mean preservation of required original sources and temporal attribution in the prompt. The fake stub always declines personal assertions, so its abstention and zero-false-assertion counts are orchestration evidence only. Semantic negative controls additionally require the complete original wording, actual source role, uncertainty metadata and the absence of the unsupported wire paraphrase; they do not measure a language model's reasoning.

Prompt bytes are actual serialized UTF-8 length. `prompt_token_upper_bound` is a conservative byte-based proxy, not tokenizer output. Mocked retrieval time, pre-generation orchestration time and full fake-chat route time are separately reported; none measures real network or inference performance. No passed test resolves the historical Windows BSOD cause.

A real LLaMA evaluation requires separate owner authorization, a fresh resource preflight and a fixed workload. Final roadmap P4 acceptance also requires the second independent MCP host example. This offline quickstart authorizes neither live inference, private-data migration, deployment, publication, P5 nor release. Review exact results and limitations in [the P4B report](product-milestone-P4B-report.md) and the [integration contract](oomp-integration.md).