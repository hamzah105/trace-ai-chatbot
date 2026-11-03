# P4B synthetic QA preregistration v1

Frozen independently before implementation tuning. All people, places, projects, parties, sources and MCP evidence are fictional. The three authenticated-owner sessions are p4b-session-0, p4b-session-1 and p4b-session-2; the fourth, foreign-owner session is a deliberate injection control and is excluded from the three-session claim.

The fixture supplies source rows and selected evidence IDs. A test may deterministically render those rows into strict public MCP wire packets and mongomock rows, but must not alter source wording, gold labels, workload inputs, scenarios, thresholds or denominator definitions to fit an implementation. A schema rendering is a test adapter, not evidence that actual OOMP retrieval ranked or returned these sources. Keep any failure and any justified fixture correction as a separately versioned amendment; do not overwrite v1.

Use deterministic fake answers and mocked MCP for initial acceptance. Assert prompt membership, verified provenance, attribution, complete exclusions, state/diagnostic values, counters and persistence, not natural-language real-model quality. Arbitrary derived text cannot be certified semantically by a linked span alone and must remain untrusted attributed evidence.

## Fixed measures

- Source recall is micro matched gold source-case pairs / 17. There are 12 scenarios, 10 with nonempty gold source sets. Deduplicate within a case; the same source in separate cases counts separately. Macro recall has 10 opportunities. Pet and foreign cases have no gold source and are excluded only from recall, not abstention or security.
- Source precision is matched relevant authorized included source-case pairs / all unique included source-case pairs. Report 0/0 as undefined if nothing was included. Report supplied valid gold availability separately from realized prompt selection. A budget-excluded gold source remains a recall miss and receives its budget reason; do not silently change the denominator.
- Cross-session continuity has five claim opportunities in the continuity case: project, explicit alias, robot, style and corrected relocation. It checks evidence/orchestration, not free-form answer quality.
- Temporal correction has one designated case and one corrected episode. Both proposal and correction are required for complete episode recall. Any completed-move assertion fails the zero-tolerance gate.
- Personal-claim abstention has four designated cases: political, pet, project-not-alias and foreign. Report expected abstention successes / 4, and all false assertion counts. A lack of pet evidence is unknown, not proof that no pet exists.
- Negative proof/semantic control denominator is exactly the control_count in negative-controls.json. Each enumerated mutation must execute at least once; report unexecuted controls. UTF-16, Unicode-code-point and UTF-8 indices must be distinguished without normalization.
- Prompt integrity is valid included proof units / all included proof units; empty is 0/0 undefined. Also report unauthorized included units and foreign controls rejected / foreign controls injected. Zero unauthorized prompt content and zero invalid accepted proofs are required.
- HTTP 413 is reported separately for legacy and opt-in mode over the identical long_eight input (one request per mode), plus oversized-current and mandatory-minimum boundary requests (one per mode where applicable). Do not aggregate unlike workload requests to conceal failures.
- Prompt bytes mean actual serialized UTF-8 bytes. Transport byte estimates and conservative byte-based model-token upper bounds are separately named proxies. Neither is tokenizer measurement. Preserve generation reserve 512, safety reserve 256 and num_predict=140 in designated workload; report each actual configured allowance.
- Latencies use perf_counter wall durations per mocked retrieval and per fake-model orchestration. Report count/min/max and individual durations without inferring real MCP/model performance.
- Publication idempotency compares unique deterministic event IDs, accepted delivery calls, stored outbox role counts and retries for one completed fake exchange plus one feedback submission. Duplicate publication writes must be zero; retry attempts are reported separately.

## Execution and evidence

No real OOMP service, MongoDB, Ollama, cloud endpoint, model download or real inference is authorized. Use mongomock and mock MCP/fake model only. Existing external-service tests must skip using a nonexistent TRACE_TEST_OOMP_PYTHON sentinel; preserve every skip reason and count. Never weaken legacy test files to avoid boundary failures.

Run baseline, focused tests and applicable regression phases sequentially in fresh result directories with fresh offline guards, synthetic HOME/temp/environment and source snapshots. Fresh controller cancellation/violation flags latch; do not remove them to resume. Use >=4 GiB available RAM and <75 percent commit for admission; abort below 1.5 GiB, at >=85 percent commit, or on stale/failed monitoring, unknown process ownership, instability or any attempted prohibited operation. Preserve failures, stdout/stderr, command, JUnit, exclusions and resource samples. No automatic retries.
