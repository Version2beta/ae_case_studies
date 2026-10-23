# Æ case studies

Reproducible Caddy, Restic, and Rclone benchmark candidates, with explicit per-arm
models/reasoning, real Æ initialization before repair, shared regression checks, and private evidence.
Python 3.10+ standard library only; no Python installation step or build is needed.

**No subject repositories, credentials, or trial logs belong in this repository.**
Sources are existing external clones. Every invocation creates new private
workspaces outside this repository; it never resets, cleans, commits, pushes,
or opens PRs in an existing checkout. The old trials remain untouched.

## Requirements

- macOS or Linux (POSIX process groups), Python 3.10+, Git, Go with a race-capable
  toolchain, and the subject dependencies already cached. Go operations use
  `GOPROXY=off`, `GOSUMDB=off`, `GOTOOLCHAIN=local`, and `-mod=readonly`.
- Pi with the documented CLI flags. The current Æ package/initialization path is
  verified with Pi 1.3.0; earlier runner checks used Pi 1.4.0. Select the intended
  executable with `--pi` and retain its version; do not conflate those results.
  Provider authentication must already be configured through approved Pi mechanisms.
  Do not pass keys as command arguments or copy auth files into this repository.
- A prebuilt installed `ae-foundation` npm package (or a built external checkout)
  with `dist/cli.js`, `integrations/pi/extension.mjs` and `prompts/init.md`.
  Set `--ae-root` to that package root; no Go compiler is needed for Æ itself.
  The runner does not install or update dependencies or rebuild Æ silently.
- Local clones containing the exact commits in `cases.json`:

| Case | Pinned revision |
|---|---|
| Caddy | `f355b8687d5582ea9fcc99f71598109d1e5b6ced` |
| Restic | `dd09b6bd01af220b1d5d95c0d4d7d472e05e05c4` |
| Rclone | `81e7372f6fbedfa80592e9a564593d63a8dc32f3` |

These intentionally reproduce the selected defect revisions, not an unspecified
“latest master.” Source clones can have unrelated work: it is not copied or
modified; only committed objects are cloned. Supply a separate committed
reference-fix checkout for local acceptance-fixture validation if desired.

## 1. Opt-in real-boundary smoke check without model charges

```sh
python3 -m unittest -v
python3 -m py_compile bench.py test_bench.py

# Adjust these external paths for your machine.
SOURCES=/Users/rob/Development/reffector/experiments
AE=/Users/rob/Development/ae-foundation
OUT=/Users/rob/Development/ae-case-study-runs

python3 bench.py check all --source-root "$SOURCES" --ae-root "$AE" --output "$OUT"
```

`check` is the opt-in real-boundary smoke path: it uses the supplied local
subject checkout and built Æ CLI, but it does not launch Pi or a hosted model.
It runs the shared regression against each baseline and requires an
**assertion-level failure** with the expected tests actually executed. Compilation
failure, timeout, skipped tests, or “no tests to run” do not qualify as baseline
reproduction. It also constructs the validated initialization prompt through Æ's
real CLI without creating a journal. No hosted model is invoked. These checks do
not exercise preparation quality or the Pi close-hook worker.

To check a committed known fix using the same frozen regression:

```sh
python3 bench.py check restic --source "$SOURCES/restic" \
  --fixed-source /Users/rob/Development/restic-pr --ae-root "$AE" --output "$OUT"
```

The same command works for Caddy and Rclone with their respective local PR
checkouts. `--fixed-source` uses that checkout's HEAD, not its uncommitted files.
See [VALIDATION.md](VALIDATION.md) for what has actually been exercised.

## 2. Initialize memory, then run candidate comparisons

`run` first creates a dedicated fresh preparation checkout at the pinned revision.
It calls Æ's read-only `prepare-prompt` and submits that shared init/update prompt
to a separately awaited Pi process with the extension loaded. The repair ticket,
repair instructions and evaluator fixture are not installed in that checkout.
Only inspection and record-only memory writes are requested; file-edit tools are
not enabled. Shell access is not a sandbox. The preparation model/reasoning matches
`--ae-model` / `--ae-thinking`.

The runner checks process/settings/accounting, anchored findings, unchanged source
and runtime, then freezes `preparation-memory.ndjson`. Preparation failure prevents
both repair arms from starting. It copies only that validated journal into a fresh
Æ repair checkout. Source repositories' existing `.ae` directories and previous
runs are neither copied nor reset. There are no small layout seeds or target-word
blacklists in this protocol. Each `run` performs fresh preparation; it does not
accumulate repair discoveries across independent benchmark candidates.

To run initialization only, without repair or Go evaluation:

```sh
python3 bench.py prepare caddy --source "$SOURCES/caddy" --ae-root "$AE" --output "$OUT" \
  --ae-model openai-codex/gpt-6.1-sol --ae-thinking high
```

`prepare` can incur model charges. It needs Node/Git/Pi, but no Go toolchain. It
uses the same initialization phase as `run`, not a separate seed generator.
Review its source/history coverage and claim accuracy; a technically valid run
is not a certificate of comprehensive knowledge.

### Run the repair pairs

**These commands incur provider charges.** They grant the agents ordinary local
read/edit/test work within newly created subject checkouts. `--offline` disables
Pi's background catalog refresh, not model requests or shell-network access.
The runner supplies scope boundaries but is **not a security sandbox**. Run only
with trusted subject source, dependencies, Pi configuration, and Æ extension.

Use the same source/Æ/output variables from step 1. Keep the Caddy model-tier
comparison; use the chosen same-model settings for the other two:

```sh
python3 bench.py run caddy --source "$SOURCES/caddy" --ae-root "$AE" --output "$OUT" \
  --control-model openai-codex/gpt-6.1-sol --control-thinking high \
  --ae-model openai-codex/gpt-5.6-luna --ae-thinking high

python3 bench.py run restic --source "$SOURCES/restic" --ae-root "$AE" --output "$OUT" \
  --control-model openai-codex/gpt-6.1-sol --control-thinking high \
  --ae-model openai-codex/gpt-6.1-sol --ae-thinking high

python3 bench.py run rclone --source "$SOURCES/rclone" --ae-root "$AE" --output "$OUT" \
  --control-model openai-codex/gpt-6.1-sol --control-thinking high \
  --ae-model openai-codex/gpt-6.1-sol --ae-thinking high
```

Any exact Pi `provider/model` IDs can be supplied independently. Different models
and reasoning levels are allowed, not treated as experimental errors. Actual
session selections must match the explicitly requested settings; a model's
silently clamped reasoning level makes a run invalid until the intended setting
is requested. A mixed-model result compares the complete setups; do not attribute
its difference to memory alone.

For identical settings across all three, use `run all --source-root "$SOURCES"`
with the same model flags. `--order ae,control` reverses order. The default is
control first, then Æ; shared caches and fixed-order effects remain limitations.

Preparation defaults: 100 completed assistant calls and 1,200 seconds, configurable
with `--preparation-max-calls` / `--preparation-timeout`. Repair defaults: 35
completed assistant calls, four consecutive tool errors, 420 seconds per agent,
and 120 seconds per evaluator command. Call/error limits
are **polled**, not atomic pre-call admission controls; an in-flight request can
finish after a limit is observed. Process groups are terminated on timeout,
limit, or interruption. Do not rerun an unchanged deterministic failure: inspect
its logs, fix its cause, then create a new candidate.

## 3. Review and explicitly select canonical runs

Each command prints a unique run directory. Review its `report.md`,
`results.json`, preparation findings/coverage/session, source changes (including
new files), actual settings, injected context, and test logs. Results are not automatically designated canonical.

```sh
python3 bench.py select "$OUT/EXACT-RUN-DIRECTORY" --output "$OUT"
```

This appends a designation to private `canonical.ndjson`; the last entry for each
case is current, and earlier designations remain in the audit trail. Nothing is
published. Only a complete valid pair with successful shared acceptance,
uncached package tests, and the configured race checks is eligible. The default
runs race tests; an explicit `--no-race` is recorded in the evaluator results and
narrows the validation claim. Model/accounting/treatment failures block selection
regardless of whether a plausible patch passes tests.

**Current known gate:** earlier Æ runs reported automatic handoff unavailable.
This runner records that warning and blocks canonical selection rather than
silently calling the full memory treatment successful. Repair/verify the handoff
path first if it reproduces. See [AE_UPDATES.md](AE_UPDATES.md). A candidate can
still report `repair_verified: true` while `valid: false`; those are different
claims. A nonzero benchmark exit is not permission to discard its evidence.

Use exactly the selected final candidate for each case-study results table.
Earlier experimental attempts may be omitted from the articles because their
protocol was superseded. Retain them privately and state briefly that pilot runs
were used to refine the protocol. Do not pick the cheapest of repeated valid runs
without disclosing that selection procedure. An invalid final candidate needs a
protocol correction, not an unreported substitution.

## Memory and ticket policy

- `cases.json` pins source revisions and common acceptance settings; it no longer
  supplies findings. Æ's general initialization prompt drives source/history
  examination and actual saves. The first authorized save creates the store.
- Preparation has no repair ticket in its workspace and must inspect only source
  and reachable local history. Do not expose previous fixes, evaluator tests,
  trial journals or drafts. Ordinary file/shell tools are not a security sandbox.
- Current-source observations must have inspected revision/file anchors; claims
  about historical changes need actual commit/diff evidence. Source-derived
  starting knowledge is not invented past decisions or session outcomes.
- Review preparation evidence, contradictions and gaps before canonical selection.
  Existing defect knowledge and model training remain possible confounds; these
  retrospective cases do not establish general ticket blindness. A naturally
  discovered relevant defect must be disclosed as prior diagnostic knowledge,
  not rejected merely because its source filename is in the repair area.
- Tickets are explicitly constructed scenarios. They omit target source paths,
  package-test commands, and invented diagnostic stack traces. They still state
  the relevant user operation. Do not call them verified customer incidents.
- Common instructions are frozen and supplied to both arms; Pi context-file
  discovery is disabled to avoid inherited `AGENTS.md` differences. Both arms
  retain the same source/docs. The Æ arm additionally gets the explicit extension
  and memory tools. Inspect the saved system/session context for other differences.

## Evidence and accounting

Artifacts stay outside this repository, with private file modes by default:

- `inputs/`: frozen runner, cases, ticket, common instructions, and evaluator
  fixture, with hashes in `results.json`.
- `workspaces/`: fresh baseline, participant, and evaluator clones. Evaluation
  fixtures are installed **after** agents finish, in separate evaluator clones.
- `*-sessions/`: persisted Pi JSONL, requested and observed model/reasoning,
  injected memory, provider usage/cost metadata. No fresh session resumes an old one.
- `*-changes/` and `*-files.json`: complete regular-file changes, including
  untracked Go tests and deletions. Symlinks/escaping paths are rejected.
- `logs/`: argv/cwd/exit/time metadata and stdout/stderr for separate commands.
  Shell exit masking is avoided in the evaluator: Go checks are direct processes.
- `preparation-prompt.md`, `preparation-result.json`, `preparation-sessions/`:
  exact initialization input, settings, execution/accounting and observed work.
- `preparation-memory.ndjson`, `memory-after-repair.ndjson`: prepared snapshot
  versus resulting repair memory. The former's hash is checked before copying;
  Æ runtime/prompt/package hashes are retained and checked for changes.
- `report.md` / `results.json`: bounded repair evidence distinct from treatment
  validity. Canonical selection stores the results hash and verifies input hashes.

Total tokens include repeated cached input. Assistant-call counts differ from
usage-event counts when compaction or other separately billed events occur.
Missing token or price metadata stays unknown; reasoning-token counts are not
invented. Provider charges are estimates, not invoices. Phase/cognitive attribution
is deliberately omitted. Repair table costs/times **exclude preparation** and
later evaluator work. Preparation usage/time/cost estimates are retained in a
separate report section and JSON object, not added to repair totals. These are
repair-only figures, not lifecycle/cold-start cost or an assumed amortization.
Human review, subscriptions, external charges, and PR preparation are unmeasured.
No general savings, causal cache explanation, production guarantee, or maintainer
approval follows from a green local run.

Do not commit raw logs, caches, source clones, or credentials. `.gitignore` is an
additional guard, not a privacy review. Use a single writer per run and designate
canonical results only after reviewing the exact archived candidate. Failed and
superseded workspaces are retained; cleanup is never automatic.
