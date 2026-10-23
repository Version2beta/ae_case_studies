# Æ updates and earlier recommendations

## Current status

Subsequent local Æ changes added streaming index inspection, classified capture
failures/session status, asserted-origin/reported-revision display, exact retrieval
receipts and explicit init/update preparation. A prebuilt npm package now contains
the CLI, Pi extension and shared preparation prompt; installed-package tests pass
with Pi 1.3.0. The runner now uses that actual initialization workflow before any
repair, rather than curated layout seeds, and retains preparation usage separately.
See [current validation](VALIDATION.md#current-init-based-protocol) and Æ's own
`docs/implementation-status.md` for acceptance boundaries. An initial Caddy
preparation attempt hit Codex quota; a later local preparation completed. Detailed
pilot results remain private, and no canonical repair pair has been run/selected.
A coverage note exceeded normal retrieval after metadata overhead; Æ's prompt now
requires short linked coverage records and explicit bounded-context readback.
No complete-history or causal real-model benefit is established.

## Earlier recommendations (historical)

The following were bounded recommendations at the earlier inspection point, not
claims that they were already implemented then. The inspected checkout
was `ae-foundation` at `28771bc6a1a13410f02f2b6c695296727f4a891d` with a clean
tracked working tree. Different/newer Æ implementations need their own check.

## 1. Diagnose and repair headless automatic handoff — first priority

**Observed:** the retained Caddy, Restic, and Rclone Æ runs repeatedly emitted
“Æ automatic handoff unavailable; inspect journal recovery/lock before retrying.”
Initial context injection worked. This does not establish that a lock caused the
failure, or that new observations survived into a later session.

**Current mechanism:** `src/handoff.ts` runs a bounded child worker and reduces
its outcome to `saved`, `absent`, or `failed`. The child stderr is ignored;
`src/handoff-worker.ts` also catches its error without returning a classified
reason. Several distinct causes therefore produce the same lock-oriented warning.

**Small update:** return a bounded, non-sensitive failure code (for example
`locked`, `capture_invalid`, `deadline`, `git_state`, or `store_io`) and record a
structured status in the session. Keep raw paths, captured prose, and exception
text private. Do not break locks, widen permissions, or weaken revise/decide
confirmation to make the warning disappear.

**Acceptance:** reproduce the real print-mode lifecycle, not just direct worker
calls. Start from a real seeded store, execute a substantive local edit/test,
settle and shut down, verify a durable handoff and idempotent close behavior,
then open a fresh session and retrieve it. Exercise lock contention, invalid
capture, timeout, and interrupted-session cases. Establish the root cause before
choosing the repair. This benchmark blocks canonical selection on the known
warning so the defect cannot be hidden behind a passing Go test.

## 2. Make provenance visible, especially reconstructed history

**Observed:** manually written seed prose was labeled “established historical
invariant” and described alleged attempted/rejected approaches without supporting
sessions or commits. The formatter displayed that prose with source anchors, but
an anchor establishes location—not the historical attempt or the truth of a claim.

**Existing support:** the domain/journal already separates source, evidence,
standing, and authority; the formatter labels context untrusted. Do not replace
those useful safeguards with another undifferentiated “fact” flag.

**Small update:** expose record origin and supporting revision/session reference
in the context/inspection view. Clearly distinguish curated source summaries,
observed session actions, historical extraction, and unverified agent reports.
A historical rejected-approach claim should retain a verifiable reference or an
explicit “unverified reconstruction” qualification; merely linking today's source
must not promote it to historical evidence. Existing records can remain intact
with accurate qualifications rather than being silently rewritten.

**Acceptance:** round-trip a curated note and a real session-derived finding,
retrieve each, and verify that origin, uncertainty, revisions, and disagreements
survive both JSON and Markdown output. Test missing or stale references.

## 3. Export the exact selected memory and its cost-relevant footprint

**Observed:** earlier case-study prose inferred which knowledge was supplied,
underestimated its size, and confused stored records with retrieved content.
Unselective or redundant memory can increase repeated cached-input costs.

**Existing support:** `ae-context` custom session messages, context snapshots,
anchors, truncation warnings, and bounded retrieval already exist. Use them.

**Small update:** add a structured retrieval receipt: query kind, selected record
IDs/revisions, truncation/omission status, content hash, and bytes/characters.
Show lexical relevance as selection, not evidence of truth. Add an explicit
configurable context budget and deduplication against already supplied context
only where measurement shows a benefit. Do not label character counts as tokens
without a tokenizer, and do not claim avoided search or saved cost from retrieval
alone. Keep full selected prose in private session evidence, not analytics logs.

**Acceptance:** deterministic selection under the configured limits, accurate
truncation and footprint, preserved qualifications, and no duplicate injection
on the same session checkpoint. Compare overhead against an equally informative
plain-text handoff before adding a new indexing system.

## 4. Distinguish initialization, history catch-up, and capture status

**Observed:** the desired `ae init`/catch-up/flight-recorder experience was
sometimes described as implemented when the available evidence showed only
prompts or empty-store initialization. `ae_status` explicitly reports counts and
a latest evidence SHA, not proof of complete ingestion.

**Small update:** report these separately: store initialized, curated seed loaded,
verified ingestion checkpoint (if implemented), last capture attempt/outcome, and
whether a resumable handoff exists. A failed save should be visible immediately,
not discovered when the next task lacks its history. If repeatable historical
catch-up is implemented, give it explicit provenance and a bounded resumable
checkpoint; do not treat an empty journal or a Git SHA alone as complete coverage.

**Acceptance:** status agrees with disk state across success, absence, partial
capture, stale revision, and failed write. Read-only inspection must not create a
store or grant knowledge authority.

## What not to build again

The inspected adapter already provides `ae_record`, `ae_status`, `ae_brag`,
`ae_context`, record-only autonomous persistence, and slash-command aliases.
The contribution receipt already disclaims causal savings/invariant-preservation
claims. Verify and repair these paths instead of adding duplicate tools.

Model/reasoning selection, preparation evidence review, canonical selection, and shared Go
acceptance fixtures belong in this benchmark repository. They are not reasons to
add benchmark-specific bug knowledge or authorization exceptions to Æ.

**Recommended order:** diagnose/fix handoffs, expose capture/provenance evidence,
then consider retrieval-budget improvements supported by measured overhead. Do
not change Æ between the two arms of a candidate run; freeze and fingerprint the
built runtime first. No new retrieval architecture is justified by these trials
alone.
