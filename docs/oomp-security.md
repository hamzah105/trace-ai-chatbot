# Stage 8 security and privacy

OOMP is optional and external. Default off mode preserves TRACE's existing behavior without importing MCP or contacting a memory service. Enabled operation is deliberately a pinned single-owner local development profile. It is not a production multi-user authentication system.

## Trust boundary

The existing TRACE API's user_id fields are ownership selectors, not authentication. Stage 8 never treats them as authority for an OOMP tenant or namespace.

Trusted server configuration pins one TRACE owner ID and one OOMP principal/tenant/namespace. Memory-enabled private routes additionally require either a purpose-bound owner cookie issued after existing verified password/Google login, or a separate local deployment key. Supplied user/session IDs must match the pin and stored Mongo ownership. Other users cannot opt into this scope.

The cookie is HttpOnly, SameSite=Strict and expires after eight hours. Because this profile is plain HTTP on literal loopback, Secure is false; no public/TLS deployment is claimed. Logout deletes the browser cookie, and successful other-account login also clears it. Cookies are stateless: logout does not revoke a copied ticket elsewhere before expiry. Rotate the owner key to revoke all outstanding tickets. A non-sensitive readable flag triggers browser logout cleanup and provides no authority itself.

Private chat, feedback, sessions/history, analytics and profile requests require a loopback peer, exact configured Host, and exact same Origin when supplied. This prevents a browser's cross-origin request or DNS-rebinding Host from using the owner credential. Existing broad CORS configuration remains for disabled-mode compatibility; it does not bypass the enabled private-route guard. Do not put this profile behind a proxy or expose it on a LAN. Local OS administrators, browser compromise and stolen deployment credentials remain trusted-host risks.

Registration/login and /health remain their ordinary routes. The memory credential is issued only after the original password check or verified Google handoff succeeds. This is a narrow integration boundary, not a replacement for TRACE's authentication design or enterprise session management. The supported entry point is backend.app:app; legacy chat-only entry points cannot manufacture verified owner state.

## Independent MCP authority

The MCP URL must use literal loopback HTTP and /mcp without userinfo, query credentials or fragments. The client disables environment proxy use and redirects, applies operation timeouts/concurrency and bounds streamed and structured responses. SDK clients and transports open/close within their own async lifecycle; no session is shared across incompatible loops.

OOMP credentials and signing keys remain environment-backed host secrets. They never appear in chat fields, localStorage, templates, logs or prompt text. TRACE's owner key must be distinct from its read token and writer credentials; signing keys must be distinct from all bearer/owner keys. Configuration files name secret environment variables, not their values. Use generated random keys; length validation cannot certify entropy.

Actual SDK discovery/input/output validation is followed by bounded local wire validation. No invented scope parameters are sent. In the Stage 7 contract, retrieval output has no signed tenant/namespace attestation: administrators must correctly provision the read token's server-side grant. TRACE does not pretend otherwise.

As a second check, every source/edge reference must link to a real Mongo interaction and owned session, expected source system, encoded session identity, role and deterministic event identity. Guessed IDs, foreign-owner proof, unrelated session links and locally excluded rows are rejected before prompt composition. An actual foreign-credential MCP test demonstrates this rejection. This is a consistency guard, not cryptographic authentication of an arbitrary malicious memory server.

## Untrusted evidence and prompt limits

Historical evidence is JSON data in a separately labeled block with provenance; it is never installed as application policy, run as code, fetched from locators or interpreted as a tool request. TRACE still invokes only Ollama /api/generate; it does not add general LLM tool calling.

Instructions explicitly distinguish recent session text from older cross-session owner evidence and remembered claims from verified facts. JSON encoding prevents a source string from structurally replacing a data field. This reduces prompt-injection exposure but cannot guarantee an LLM will semantically ignore every malicious instruction in a single generate prompt. Authorization, ingestion approval, erasure prohibition and all privileged decisions remain outside the model, even if its answer is influenced.

The byte-accounted context packet must match the advertised memories and remain within its budget. Complete memories with nonpositive relevance are omitted, and complete historical objects that exceed the prompt cap are dropped. Recent context is never silently clipped. An over-cap recent prompt receives 413 in enabled mode. UTF-8 units are conservative proxies, not exact tokenizer counts; generation reserve, instruction overhead and configured num_ctx are accounted separately.

Malformed, wrong-owner or oversized evidence is never passed to the model. Service/timeout/authentication failures produce sanitized operational codes and the original recent prompt. Authorization failure never retries with a broader token. The successful user-facing response shape stays unchanged.

New ordinary logs contain static integration codes, never raw questions, memory bodies, response envelopes or secrets. The adapter also applies an operation-local filter to SDK diagnostics because parser exception tracebacks can otherwise include remote validation input. This does not change other callers' logging. Synthetic malformed-response and private-query tests verify suppression. Do not treat ordinary-log redaction as encryption of MongoDB, prompts or the underlying local machine.

## Host-approved publication

Only explicit retrieve_and_ingest mode and verified owner activity stage new consent. Source roles are derived from persisted record fields, not from model choices: user_message/user, assistant_message/assistant, feedback/user after successful submission. Assistant output is never relabeled as a verified user statement.

The trusted host reproduces only the published Stage 7 HMAC approval wire format. Its separate secret signs principal/scope/source policy, exact event/provenance, nonce and expiry. OOMP independently validates this and performs immutable append. The model cannot access a signing tool, choose grants, approve a conflict, erase memory or send arbitrary canonical/SQL writes.

An enabled server and possession of a writer token alone are insufficient. The host's policy consists of explicit deployment approval, authenticated owner input, successful authoritative Mongo persistence and accurate role/source mapping. This is application policy approval, not a claim that a human clicked approval for each event. Treat configuring full mode and signing keys as deliberate consent to publishing eligible new records.

MongoDB holds a small embedded outbox, completion/consent policy and exclusion marker. It does not become a replacement long-term memory database. Marker creation/completion and per-role conditional state updates are atomic in one document; updating session bookkeeping, Mongo interaction state and external SQLite is not one distributed transaction.

A missing completion marker after a crash is deliberately not promoted as successful. Full-mode authoritative completion must persist before a successful chat result is returned; a failure of that local Mongo write is a storage failure, not an OOMP outage. Once completion is durable, missing outbox entries can be reconstructed without source-body copies. Feedback remains authoritative after its original successful update even if optional scheduling fails.

Delivery is at least once with scoped leases/fences, bounded attempts/backoff and OOMP idempotency. Acceptance-before-acknowledgement uncertainty is safe to replay. Exhausted uncertain states are failed and visible rather than falsely delivered. A delivery result never claims OOMP extraction finished; the external Mind worker must run explicitly. Original content changed by an external writer causes conflicts instead of silently rewriting evidence.

## Privacy policy and legacy history

Automatic reconciliation handles only already-approved completed records under the same configured policy. Legacy records are not imported at startup. Backfill requires an explicit pinned owner, bounded page, dry-run review and separate --approve. Other-user, invalid and failed-staged records are skipped.

A local exclusion marker prevents later scheduling, reconciliation or legacy reconsent and rejects that record's proof in prompts. It is persistent application policy, not OOMP erasure. It cannot recall previously returned data or an already accepted/in-flight delivery. If a record has independently endorsed surviving evidence, OOMP's existing policy remains authoritative.

Remote erasure, conflict approval, entity merging and scope mutation are not added. Administrative OOMP privacy operations remain separate, local and explicitly controlled. SQLite and MongoDB remain plaintext; copied prompts, backups, exports and already generated responses require the operator's retention policy. This milestone does not promise cryptographic deletion or production retention enforcement.

## Tested scope and remaining limits

Tests cover actual separate-service MCP, correctly and incorrectly scoped credentials, owner cookie/header protection, default-off SDK independence, raw SDK error-log suppression, bounded network faults, source proof/packet validation, roles/signatures, idempotency, concurrency, recovery, exclusion and unchanged feedback/session/analytics behavior. A separate isolated real MongoDB database validates persistence/reopen. Two synthetic real llama3 generation calls succeeded. The recall experiment uses a model mock and records actual prompts; no accuracy improvement is claimed.

Existing session mutation/finalization coordination remains process-local: run one TRACE application worker and avoid external direct history edits. A separate explicit publication worker is safe through Mongo fencing, but this is not a multi-server production system. No desktop browser visual acceptance, public OAuth memory flow, network proxy/TLS configuration or arbitrary multi-user scope mapping was certified.

See [operation guide](oomp-integration.md), [validation](stage8-validation.md) and [completion report](stage-8-report.md). OOMP source remains unchanged; Stage 9 research and Stage 10 release work are not implemented.