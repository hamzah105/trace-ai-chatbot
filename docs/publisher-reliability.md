# Publication validation and current-request priority

Malformed legacy feedback values previously raised `AttributeError` during
publication reconciliation. Feedback is now validated as an object (or absent)
through the existing `invalid_source` contract. Reconciliation counts the invalid
row without modifying or discarding it. A claimed invalid feedback event becomes
permanently failed through the existing lease fence and is not retried; valid
user/assistant roles retain their own eligible delivery paths.

Consent, owner/session checks, event identity, signed approval, durable receipts,
attempt limits, uncertain acknowledgements and failed-event exclusion are
unchanged. No backfill, migration, credential change or automatic failed-event
revival is introduced. The OOMP companion handles only bounded transient Mongo
connection recovery and retains sanitized supervisor failure details.

Context V1's policy now distinguishes the current user request from quoted recent
and historical data. The current request's topic exclusions, corrections and
brevity guide the answer; quoted context cannot override it. Greetings and
self-contained questions should receive normal answers without narration of
retrieval state. Complete source text, feedback, Unicode, strict provenance and
prompt/context budgets remain mandatory. This wording change is not evidence
that a real model obeyed it; actual answer quality and completion stop reasons
require a separately approved resource-gated LLaMA test.

Keep the repair isolated from a running Uvicorn `--reload` checkout. Source edits
can cause an automatic application reload and its existing index checks. Review
the separate OOMP and TRACE branches before deployment. Pinned publication code
requires an explicitly authorized profile approval refresh; never bypass the
existing fingerprint guard or overwrite a signed handoff to make startup pass.

No live profile or conversation is used for acceptance. Synthetic record controls
and authenticated source-to-prompt checks are reported separately from model
answers and historical live incidents. The historical publication exception
remains unproven; reproducing a failure mode does not establish its occurrence in
the owner's earlier run.
