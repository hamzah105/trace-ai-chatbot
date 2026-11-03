# TRACE P4B hosted CI policy

3 November 2026 (Asia/Karachi). CI-only work from accepted P4B 5b333aa20537b8771102f13266185e3fc2e349a2; no runtime or frozen fixture changes.

## Classification recorded before the workflow

All 256 test function/method definitions were inspected statically before workflow creation (parameterized instances are counted by pytest). tools/ci_policy.json pins the nine service-dependent exclusions. No remaining test requires real inference, private credentials or an OOMP installation; ordinary app model and OAuth calls are mocked.

| Exact excluded node | Reason |
| --- | --- |
| `tests/test_oomp_context.py::test_actual_invalid_mcp_credentials_are_explicit` | External OOMP MCP installation and listener |
| `tests/test_oomp_end_to_end.py::test_actual_client_discovery_and_status` | External OOMP MCP installation and listener |
| `tests/test_oomp_end_to_end.py::test_long_history_baseline_vs_mcp_with_original_latest_eight` | External OOMP MCP, worker and SQLite store |
| `tests/test_oomp_end_to_end.py::test_wrong_credential_scope_response_is_rejected_over_real_mcp` | External OOMP MCP and worker |
| `tests/test_oomp_end_to_end.py::test_independent_sync_clients_own_separate_async_lifecycles` | External OOMP MCP installation and listener |
| `tests/test_oomp_feedback.py::test_owner_cross_session_recall_requires_stored_owner_link` | External OOMP MCP and worker |
| `tests/test_oomp_publisher.py::test_real_mcp_roles_idempotency_feedback_and_approval_tampering` | External OOMP MCP, worker and SQLite store |
| `tests/test_oomp_publisher.py::test_actual_service_outage_restart_and_durable_replay` | External OOMP MCP restart and SQLite store |
| `tests/test_oomp_publisher.py::test_real_mongo_outbox_survives_client_reopen_and_replay` | Physical MongoDB port27017 read/write/drop |

## Every remaining module

| Module | Classification |
| --- | --- |
| `tests/test_google_oauth.py` | synthetic/mocked; no physical Mongo, inference or private credentials |
| `tests/test_oomp_client.py` | synthetic owned loopback fault/refusal fixture; no OOMP/model service |
| `tests/test_oomp_context.py` | excluded: External OOMP MCP installation and listener; synthetic owned loopback fault/refusal fixture; no OOMP/model service; synthetic/mocked; no physical Mongo, inference or private credentials |
| `tests/test_oomp_end_to_end.py` | excluded: External OOMP MCP and worker; excluded: External OOMP MCP installation and listener; excluded: External OOMP MCP, worker and SQLite store |
| `tests/test_oomp_feedback.py` | excluded: External OOMP MCP and worker; synthetic/mocked; no physical Mongo, inference or private credentials |
| `tests/test_oomp_publisher.py` | excluded: External OOMP MCP restart and SQLite store; excluded: External OOMP MCP, worker and SQLite store; excluded: Physical MongoDB port27017 read/write/drop; synthetic/mocked; no physical Mongo, inference or private credentials |
| `tests/test_oomp_security.py` | synthetic/mocked; no physical Mongo, inference or private credentials |
| `tests/test_p4b_allocator.py` | synthetic/mocked; no physical Mongo, inference or private credentials |
| `tests/test_p4b_diagnostics.py` | synthetic/mocked; no physical Mongo, inference or private credentials |
| `tests/test_p4b_environment.py` | synthetic/mocked; no physical Mongo, inference or private credentials |
| `tests/test_p4b_evaluation.py` | synthetic/mocked; no physical Mongo, inference or private credentials |
| `tests/test_p4b_orchestration.py` | synthetic/mocked; no physical Mongo, inference or private credentials |
| `tests/test_p4b_protocol.py` | synthetic/mocked; no physical Mongo, inference or private credentials |
| `tests/test_phase2.py` | synthetic/mocked; no physical Mongo, inference or private credentials |
| `tests/test_phase3_analytics_data.py` | synthetic/mocked; no physical Mongo, inference or private credentials |
| `tests/test_phase3_charts.py` | synthetic/mocked; no physical Mongo, inference or private credentials |
| `tests/test_phase3_dashboard_frontend.py` | synthetic Node frontend; platform-portable with pinned Node |
| `tests/test_phase3_dashboard_routes.py` | synthetic/mocked; no physical Mongo, inference or private credentials |
| `tests/test_phase3_finalization.py` | synthetic/mocked; no physical Mongo, inference or private credentials |
| `tests/test_phase3_finalization_frontend.py` | synthetic Node frontend; platform-portable with pinned Node |
| `tests/test_phase3_finalization_integration.py` | synthetic/mocked; no physical Mongo, inference or private credentials |
| `tests/test_phase3_metrics.py` | synthetic/mocked; no physical Mongo, inference or private credentials |
| `tests/test_phase3_metrics_routes.py` | synthetic/mocked; no physical Mongo, inference or private credentials |
| `tests/test_phase3_tables.py` | synthetic/mocked; no physical Mongo, inference or private credentials |
| `tests/test_phase3_tables_routes.py` | synthetic/mocked; no physical Mongo, inference or private credentials |

The two frontend modules contain eight checks and require Node. The legacy byte-comparison test needs the public repository commit6976c51; checkout must fetch history. Existing D:/Desktop/OOMP paths are confined to the explicitly excluded external fixture; a nonexistent sentinel and runtime guards prevent discovery or launch. PyWin32 is a Windows-only transitive SDK dependency; no test is intentionally skipped by OS.

## Planned checks and boundaries

Four Windows/Ubuntu Python3.11/3.12 jobs install declared CI requirements, check dependencies and frozen bytes, then run the broader synthetic Python suite and frontend checks in separate guarded phases. Nine service tests are deselected before fixtures run, with exact IDs and reasons written to accounting. No fallback to implicit service skips, real secrets or workstation paths. New external fixtures not listed in policy fail collection.

The test bootstrap suppresses dotenv, clears ambient credentials/environment, uses synthetic home/temp and denies real model/Mongo/OOMP endpoints, external networking, private files, OOMP/provider imports and unreviewed executables. Only owned ephemeral loopback fault fixtures, the exact read-only git-show comparison and guarded Python/Node children are permitted. Guards are CI tooling, not application runtime protections. Hosted installation can access public package sources before tests; test execution stays offline. No services or model weights are installed.

Frozen JSON/preregistration bytes remain unchanged. The two metadata documents permit only the previously approved Git CRLF/LF equivalence and retain pinned normalized checksums; all six manifest entries use original byte-count/SHA-256 assertions.

Results below will distinguish local workflow validation from actual hosted execution. Real OOMP integration, physical Mongo persistence, LLaMA answer quality and the second independent MCP host remain separate owner-authorized gates. This task does not start P5.

## Local validation findings before publication

Initial static parsing caught a YAML plain-scalar colon in the binary-only pip command; it was converted to a block scalar before tests. The first runner startup caught a missing stdlib sysconfig import, corrected before collection. Both failed versions/results remain under ignored data/hosted-ci-20261102T1939234160736Z.

The first complete local run reported 397 passed, one failed, nine explicitly deselected and55 unittest subcases. The unchanged stalled-network timeout test observed2.438s on first optional-SDK use: the production client imports MCP outside its asyncio timeout. The CI policy now executes the existing dependency-readiness test first, then retains the unchanged2s stalled-network assertion. Its import duration is recorded separately in accounting. This validates installed SDK availability and warm transport deadlines, not a cold-start latency guarantee; no app or original test code was changed to conceal the limitation.
## Local pre-push result

Windows/Python3.11.4 with the reviewed read-only dependency environment: synthetic Python phase390 passed plus55 unittest subcases,17 deselected (nine service exclusions plus eight frontend phase selections), zero skips; frontend phase8 passed,399 deselected (nine service exclusions plus390 Python phase selections), zero skips. Source snapshots stayed unchanged and frozen integrity passed before/after both phases. New controller artifacts are under ignored data/hosted-ci-20261102T1939234160736Z. This is local validation, not a fresh-install or Python3.12/Ubuntu claim.

The workflow has a four-job OS/Python matrix,20-minute job timeout,900-second phase deadlines, owned child-tree cancellation, least-privilege contents:read, no repository secret inputs and SHA-pinned reviewed actions. PR events validate the head; push events cover main only to avoid duplicate branch/PR matrices. Checkout fetches the public history with credential persistence disabled. Python runs use isolated/no-site startup and declared dependency paths, including PyWin32's plain import directories on Windows; no old .pth/startup hooks execute. Node24.14.1 uses the reviewed frontend guard. Pip installs binary distributions only from requirements-ci.txt (pins the declared dev dependency closure, with Windows/Linux conditional dependencies); pip check and version inventories make install failures visible.

Action pins were resolved and action.yml reviewed in the official actions repositories: checkout11d5960a326750d5838078e36cf38b85af677262, setup-python a26af69be951a213d495a4c3e4e4022e16d87065, setup-node49933ea5288caeca8642d1e84afbd3f7d6820020, upload-artifact ea165f8d65b6e75b540449e92b4886f43607fa02. Test evidence uploads include only selected synthetic results/accounting/versions/logs; home/temp/credential fixtures are excluded. There is no package/model/provider cache or service setup.

Hosted conclusions must be taken from the actual run for the pushed CI head SHA. Local passing results do not certify them. Existing accepted reports remain historical; this document does not revise their prior no-hosted-CI statements. No P4B app, original test assertion, fixture or expected hash is changed by this CI-only patch. General live MCP, physical durability, cold-start deadline and model-answer quality remain unproven.

## Owner-approved POSIX ZIP guard correction

The first hosted run 41514330049 remains preserved: both Windows jobs passed and both Ubuntu jobs stopped before collection in metadata ZIP discovery. The original diagnostics deliberately omitted the denied pathname.

CPython's trusted startup configuration builds the POSIX archive landmark from its platform library directory and running major/minor version under the interpreter prefix ([3.11.17 getpath](https://github.com/python/cpython/blob/v3.11.17/Modules/getpath.py#L183), [3.12.15 getpath](https://github.com/python/cpython/blob/v3.12.15/Modules/getpath.py#L183)). The CI guard now derives exactly BASE/sys.platlibdir/pythonXY.zip from canonical sys.base_prefix and sys.version_info; it does not derive permissions from arbitrary sys.path entries. The expected leaf stays lexical: a requested path is canonicalized by the unchanged guard, so a symlink into a private or unapproved location fails equality. An absent expected archive is admitted only for its read attempt so native FileNotFoundError can proceed.

This exact-file admission follows existing credential/.env denials and the write rejection. No directory grant, wildcard, new mutation permission or change to Windows ZIP rules, network, subprocess, dotenv or model restrictions is included.

tools/test_ci_guard.py compiles the actual guard policy definitions in synthetic namespaces and runs 20 focused checks, separately from the unchanged 390 Python/8 frontend application counts and 55 legacy subtests. Probes cover exact/absent candidate reads, siblings, other versions, parent/descendant paths, private files, all write flags, mutations, synthetic canonicalized symlink escapes, Windows behavior, forbidden ports, external DNS/network, subprocesses, dotenv and live-runtime imports. No private file is opened. Each hosted job records its independently derived trusted interpreter configuration and confirms the POSIX candidate is already in isolated startup sys.path; membership verifies configuration and is not an authorization source.

Only the CI bootstrap, this focused test, its workflow invocation and this documentation are changed. Application code, existing P4B tests, requirements, attributes, fixture data and expected hashes remain unchanged. Fresh local/hosted outcomes must be taken from their separately identified new evidence; this section does not claim that the previous Ubuntu runs executed tests.

Local correction validation: 20 focused policy tests passed on Python 3.11.4 and 20 on Python 3.12.6. The initial focused run exposed five synthetic path-double errors (not guard failures); that log is preserved and the doubles were corrected without changing guard policy. Sequential guarded Python 3.11.4 validation passed 390 application tests plus 55 legacy subtests and 8 frontend checks, with the same nine service exclusions and zero skips. Frozen integrity and source snapshots passed. AST review on both Python versions confirms all original guard behavior is unchanged after subtracting the one candidate assignment and exact read comparison; synthetic before/after probes reproduce original denial of both versioned POSIX candidates. Evidence is retained under ignored data/ci-zip-20261102T2020038893253Z. Hosted POSIX configuration and application execution still require the fresh four-job run for the new commit.
