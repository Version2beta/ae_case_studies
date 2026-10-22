# Æ case studies

Reproducible Caddy, Restic, and Rclone benchmark candidates, with explicit per-arm
models/reasoning, screened memory, shared regression checks, and private evidence.
Python 3.10+ standard library only; no Python installation step or build is needed.

**No subject repositories, credentials, or trial logs belong in this repository.**
Sources are existing external clones. Every invocation creates new private
workspaces outside this repository; it never resets, cleans, commits, pushes,
or opens PRs in an existing checkout. The old trials remain untouched.

## Requirements

- macOS or Linux (POSIX process groups), Python 3.10+, Git, Go with a race-capable
  toolchain, and the subject dependencies already cached. Go operations use
  `GOPROXY=off`, `GOSUMDB=off`, `GOTOOLCHAIN=local`, and `-mod=readonly`.
- Pi with the documented CLI flags; validated locally with Pi 1.4.0. Provider
  authentication must already be configured through approved Pi mechanisms.
  Do not pass keys as command arguments or copy auth files into this repository.
- A **built** external `ae-foundation` checkout with `dist/cli.js` and
  `integrations/pi/extension.mjs`. Follow that checkout's build instructions.
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
reproduction. It also creates and queries the screened seed through Æ's real CLI.
No hosted model is invoked. These checks do not exercise the Pi close-hook worker.

To check a committed known fix using the same frozen regression:

```sh
python3 bench.py check restic --source "$SOURCES/restic" \
  --fixed-source /Users/rob/Development/restic-pr --ae-root "$AE" --output "$OUT"
```

The same command works for Caddy and Rclone with their respective local PR
checkouts. `--fixed-source` uses that checkout's HEAD, not its uncommitted files.
See [VALIDATION.md](VALIDATION.md) for what has actually been exercised.

## 2. Run the final candidate comparisons

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

Default limits: 35 completed assistant calls, four consecutive tool errors,
420 seconds per agent, and 120 seconds per evaluator command. Call/error limits
are **polled**, not atomic pre-call admission controls; an in-flight request can
finish after a limit is observed. Process groups are terminated on timeout,
limit, or interruption. Do not rerun an unchanged deterministic failure: inspect
its logs, fix its cause, then create a new candidate.

## 3. Review and explicitly select canonical runs

Each command prints a unique run directory. Review its `report.md`,
`results.json`, source changes (including new files), actual settings, injected
context, and test logs. Results are not automatically designated canonical.

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

- `cases.json` contains **manually curated package-layout summaries**, with pinned
  source anchors. They are not presented as organically earned session history.
- A fresh `.ae` journal is created through the trusted CLI with record-only
  authority. No old subject `.ae` store is copied. `ae init` here means empty
  initialization, not a verified historical catch-up operation.
- Restic excludes the capability identifier, atomic-replacement discussion,
  pre-deletion hazards, rollback language, target implementation filename, and
  config/migration hints from the seed—not just one exact string. Other cases
  similarly exclude the known target implementation and solution clues.
- Screening covers curated seed content, generated initial journal, and actual
  initial `ae-context` messages. It is a regression guard, **not proof that all
  semantic leakage is impossible**. Seeds were authored after these defects
  were known; this limitation cannot be retroactively removed by word filtering.
- Tickets are explicitly constructed scenarios. They omit target source paths,
  package-test commands, and invented diagnostic stack traces. They still state
  the relevant user operation. Do not call them verified customer incidents.
- Common instructions are frozen and supplied to both arms; Pi context-file
  discovery is disabled to avoid inherited `AGENTS.md` differences. Both arms
  retain the same source/docs. The Æ arm additionally gets the explicit extension
  and memory tools. Inspect the saved system/session context for other differences.

## Evidence and accounting

Artifacts stay outside this repository, with private file modes by default:

- `inputs/`: frozen runner, cases, ticket, common instructions, seed, and evaluator
  fixture, with hashes in `results.json`.
- `workspaces/`: fresh baseline, participant, and evaluator clones. Evaluation
  fixtures are installed **after** agents finish, in separate evaluator clones.
- `*-sessions/`: persisted Pi JSONL, requested and observed model/reasoning,
  injected memory, provider usage/cost metadata. No fresh session resumes an old one.
- `*-changes/` and `*-files.json`: complete regular-file changes, including
  untracked Go tests and deletions. Symlinks/escaping paths are rejected.
- `logs/`: argv/cwd/exit/time metadata and stdout/stderr for separate commands.
  Shell exit masking is avoided in the evaluator: Go checks are direct processes.
- `seed-before.ndjson`, `seed-after.ndjson`: initial versus resulting memory;
  Æ source/runtime hashes before the run and an unchanged check afterward.
- `report.md` / `results.json`: bounded repair evidence distinct from treatment
  validity. Canonical selection stores the results hash and verifies input hashes.

Total tokens include repeated cached input. Assistant-call counts differ from
usage-event counts when compaction or other separately billed events occur.
Missing token or price metadata stays unknown; reasoning-token counts are not
invented. Provider charges are estimates, not invoices. Phase/cognitive attribution
is deliberately omitted. Agent time excludes later evaluator work. Seed curation,
human review, subscriptions, external charges, and PR preparation are unmeasured.
No general savings, causal cache explanation, production guarantee, or maintainer
approval follows from a green local run.

Do not commit raw logs, caches, source clones, or credentials. `.gitignore` is an
additional guard, not a privacy review. Use a single writer per run and designate
canonical results only after reviewing the exact archived candidate. Failed and
superseded workspaces are retained; cleanup is never automatic.
