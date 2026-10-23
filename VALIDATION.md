# Validation record

## Current init-based protocol

The runner now invokes Æ's real shared initialization workflow before repair,
with a separate ticket-free preparation checkout/session and no curated seed.
Preparation usage is retained separately and excluded from repair-only figures.
`prepare` runs that phase alone; `check` validates read-only prompt construction
without launching a model or creating a journal. Installed npm packages are
supported as `--ae-root`, including prompt/package/runtime fingerprints.

Current local validation: Python compilation and **25 unit/process-integration
tests passed**. These include failure before either repair arm when preparation
changes source, unchanged original sources, a frozen snapshot copied into a fresh
repair checkout, separate preparation/repair accounting, and no-model checks.
Pi/Node/Go doubles remain explicitly doubles. Æ's latest separate validation
passed **149 ordinary tests and 13 real Pi 1.3.0 host tests**, with the host suite
also passing against the installed tarball, including package loading and the
CLI-generated headless preparation prompt. It caught an
npm executable-symlink bug (fixed) and Pi print-mode slash dispatch returning before
a model turn (print slash init now refuses; the caller submits/awaits the shared
prompt as an ordinary Pi run).

The first real Caddy preparation attempt through the installed package failed
before inspection: Codex reported its usage limit reached. The retained session
reports one error response and zero usage tokens/cost; those are provider metadata,
not an invoice. That attempt saved no findings and launched no repair arms.
Historical failure artifact:
`/Users/rob/Development/ae-foundation-validation/caddy-init-comparison-20261022T214835Z/runs/20261022T214835Z-caddy-prepare-3e4b1922`.
Do not retry unchanged quota failures or quietly switch provider/model settings.

Fresh real `check all` against the installed package passed for Caddy, Restic and
Rclone: each baseline reached its intended regression assertions and each
`prepare-prompt` invocation succeeded without creating `.ae`. No reference fix
or model was run by these checks. Evidence and unit-test logs:
`/Users/rob/Development/ae-case-study-validation/init-protocol-checks-20261022T215151Z`.

A later local Caddy preparation completed. Detailed pilot results and the
qualitative memory comparison remain private, not canonical publication data.
It exposed a coverage note that fit the save-input limit but not the ordinary
8,000-byte context response including metadata. Æ's preparation prompt now calls
for coverage text of at most 2,000 UTF-8 bytes per record, a short index with
separately queryable history/gaps/next-step subjects, and readback confirming saved
statement IDs and text. The regression preserves the oversized record and checks
retrieval of short linked records without raising limits or writing on readback.
The updated installed prompt is tested; hosted-model compliance has not been rerun.

No canonical init-based repair pair has been run/selected. Comprehensive coverage,
repeat-init quality and causal repair benefit remain unestablished.

## Earlier seed-protocol validation (historical)

The records below describe the superseded seed protocol, not current init-based
acceptance. Their exact artifacts remain useful provenance; old test counts and
known gaps must not be represented as current validation.

Date: 2026-10-22. Local environment: macOS arm64, Go 1.27.2, Pi 1.4.0,
external `ae-foundation` at `28771bc6a1a13410f02f2b6c695296727f4a891d`.
No hosted-model benchmark was launched. No subject checkout or PR was modified.

## Runner checks

Commands from this repository:

```sh
python3 -m py_compile bench.py test_bench.py
python3 -m unittest -q
```

Result: **25 tests passed**. Tests cover accounting/unknown metadata, actual
model/reasoning validation, required/absent memory, provider error handling,
separately billed compaction, malformed/incomplete session data, latched error
limits, timeout termination, screened seeds, preservation of existing workspaces,
untracked-file capture, symlink rejection, assertion-level baseline detection,
canonical-selection gates, changed-evidence rejection, the no-model `check`
workflow's seed/query and artifact-hash boundaries, arm-result serialization,
and arm-specific Æ extension-failure classification.

Three process-boundary integration tests use real temporary Git repositories and
subprocesses with **fake Pi/Go/Node executables**. They exercise a complete pair,
separate evaluation clones, different per-arm settings, output preservation,
canonical designation, refusal after an Æ handoff warning, and the no-model
`check` seed/query workflow. They do not prove real model behavior, real Pi or Æ
extension lifecycle, or full Go integration.
Disposable Git test fixtures create their own objects; no commit is made to this
repository or a subject checkout.

The legacy `restic-trial/run_benchmark.py --help` successfully forwards to the new
CLI. Its previous implementation was preserved privately before replacement.

## Real Go regressions and Æ CLI checks

Each was run as:

```sh
python3 bench.py check CASE \
  --source /Users/rob/Development/reffector/experiments/CASE \
  --fixed-source /Users/rob/Development/CASE-pr \
  --ae-root /Users/rob/Development/ae-foundation \
  --output /Users/rob/Development/ae-case-study-validation
```

All three commands exited **0**. Each baseline command exited **1** with executed
regression tests failing at the intended assertions. The same fixture passed on
the committed reference fix, exit **0**. CLI empty initialization, four record-only
seed operations, seed screening, and a query all succeeded for each case.

| Case | Baseline tests | Fixed tests | Reference fix HEAD | Artifact directory |
|---|---|---|---|---|
| Caddy | setup cleanup: fail | pass | `923c3c3b20424c1ab0a0511c40f162d182da6ead` | `20261022T203445Z-caddy-check-2869d117` |
| Restic | config preservation: fail | pass | `f9d2d3b2603fe88d49e2d5f3850b3ca8e3de78de` | `20261022T203445Z-restic-check-4114a8a0` |
| Rclone | producer failure + concurrent close: fail | both pass | `eaadb88cd150523db72b26c4a160c1b1cf50db2f` | `20261022T203445Z-rclone-check-0af99bc8` |

Private artifact parent:
`/Users/rob/Development/ae-case-study-validation/`.
Each directory retains frozen inputs, manifests, exact commands, and Go JSON
output. The baseline SHAs are the pins in `cases.json`.

Runner SHA-256 for those three checks:
`ca59247092fc44446f5ab71b8a53b0743aa8c3d87578aacac5723d10c7cb8f88`.

An earlier local seed check failed because the new runner initially supplied a
microsecond timestamp exceeding Æ's 24-character contract. The runner now emits
millisecond UTC timestamps. That failed artifact was retained; the corrected
checks above passed. This was harness development, not an agent result.

## Still unverified

- A real paid final pair under this exact consolidated runner, including actual
  injected memory, provider metadata, limit behavior under real model latency,
  and the final Pi close-hook outcome.
- Durable automatic handoff and retrieval by a subsequent real session. Prior
  runs reported failure; this runner blocks canonical selection on that warning.
- Candidate-specific uncached package/race results. Those run after each future
  agent pair; the `check` commands above validate the shared fixtures, not those
  future patches. No full-project suite or real-network production claim is made.
- General efficacy, causal savings, natural historical-memory quality, statistical
  significance, or cumulative economics. The curated layout seed is intentionally
  modest and was authored after the defects were known.

**Canonical status:** none selected. The writing drafts have pending final-result
tables. Superseded pilots remain private protocol history, with the Caddy
Luna-versus-Sol observation retained explicitly as historical background.
