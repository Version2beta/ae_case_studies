#!/usr/bin/env python3
"""Local, stdlib-only runner. Never reset existing workspaces or mutate remotes."""
import argparse
import contextlib
from dataclasses import asdict, dataclass, field, is_dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
THINKING = ('off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max')
TOKEN_FIELDS = ('input', 'output', 'cacheRead', 'cacheWrite')
AE_TOOLS = 'ae_context,ae_status,ae_record,ae_propose,ae_discard,ae_apply,ae_recommend,ae_brag'


def json_value(value):
    if is_dataclass(value):
        return json_value(asdict(value))
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


def dump(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(json_value(value), stream, indent=2, allow_nan=False)
        stream.write('\n')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def within(path, parent):
    return path.resolve().is_relative_to(parent.resolve())


def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args], timeout=30).decode().strip()


def safe_relative(name):
    path = Path(name)
    if path.is_absolute() or not path.parts or any(p in ('.', '..') for p in path.parts):
        raise ValueError('Unsafe repository-relative path')
    if path.parts[0] in ('.git', '.ae', '.pi'):
        raise ValueError('Protected repository path')
    return path


@dataclass(frozen=True)
class CaseSpec:
    revision: str
    package: str
    packages: str
    implementation_prefix: str
    fixture_destination: str
    tests: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value):
        return cls(
            revision=value['revision'], package=value['package'], packages=value['packages'],
            implementation_prefix=value['implementation_prefix'],
            fixture_destination=value['fixture_destination'], tests=tuple(value['tests']),
        )


def case_spec(value):
    return value if isinstance(value, CaseSpec) else CaseSpec.from_mapping(value)


def load_case(case):
    return CaseSpec.from_mapping(json.loads((ROOT / 'cases.json').read_text())[case])


@dataclass(frozen=True)
class ArmSettings:
    name: str
    model: str
    thinking: str


@dataclass(frozen=True)
class ProcessResult:
    command: list[str]
    cwd: str
    exit_code: int | None
    stop_reason: str | None
    seconds: float

    def __getitem__(self, key):
        return getattr(self, key)


def arm_settings(args, arm):
    return ArmSettings(arm, getattr(args, arm + '_model'), getattr(args, arm + '_thinking'))


def result_value(result, name):
    return result[name] if isinstance(result, dict) else getattr(result, name)


def result_mapping(result):
    return json_value(result)


def succeeded(result):
    return result_value(result, 'exit_code') == 0 and result_value(result, 'stop_reason') is None


def read_events(path, live=False):
    data = path.read_bytes()
    lines = data.splitlines(keepends=True)
    events = []
    for index, line in enumerate(lines):
        if live and index == len(lines) - 1 and not line.endswith(b'\n'):
            break  # A live writer may have an incomplete final line.
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError('Session entry must be an object')
        events.append(value)
    return events


def live_stop(session_dir, max_calls, max_errors):
    files = list(session_dir.glob('*.jsonl'))
    if len(files) > 1:
        return 'multiple_sessions'
    if not files:
        return None
    calls = streak = peak = 0
    for event in read_events(files[0], live=True):
        message = event.get('message', {})
        if message.get('role') == 'assistant' and message.get('usage'):
            calls += 1
        if message.get('role') == 'toolResult':
            streak = streak + 1 if message.get('isError') else 0
            peak = max(peak, streak)
    if peak >= max_errors:
        return 'tool_error_limit'
    if calls >= max_calls:
        return 'call_limit'
    return None


def stop_group(process):
    # Also terminate descendants if the parent already exited.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)


def process(command, cwd, log, timeout, monitor=None, input_path=None):
    start = time.monotonic()
    reason = None
    env = dict(os.environ, GOPROXY='off', GOSUMDB='off', GOFLAGS='-mod=readonly',
               GOTOOLCHAIN='local', RCLONE_CONFIG=os.devnull,
               PI_OFFLINE='1', PI_SKIP_VERSION_CHECK='1')
    with contextlib.ExitStack() as stack:
        out = stack.enter_context(log.with_suffix('.stdout').open('xb'))
        err = stack.enter_context(log.with_suffix('.stderr').open('xb'))
        stdin = stack.enter_context(input_path.open('rb')) if input_path else subprocess.DEVNULL
        child = subprocess.Popen(command, cwd=cwd, env=env, stdin=stdin,
                                 stdout=out, stderr=err, start_new_session=True)
        try:
            while child.poll() is None:
                if time.monotonic() - start >= timeout:
                    reason = 'timeout'
                    break
                if monitor:
                    try:
                        reason = monitor()
                    except (ValueError, OSError):
                        reason = 'invalid_session'
                    if reason:
                        break
                time.sleep(0.1)
        finally:
            stop_group(child)
    result = ProcessResult(command, str(cwd), child.returncode, reason, round(time.monotonic() - start, 3))
    dump(log.with_suffix('.json'), result)
    return result


def checked(command, cwd, log, timeout=120, input_path=None):
    result = process(command, cwd, log, timeout, input_path=input_path)
    if not succeeded(result):
        raise RuntimeError(f'Local operation failed; inspect {log.name} logs')
    return result


def clone(source, target, revision, logs):
    if target.exists():
        raise ValueError('Refusing an existing workspace')
    checked(['git', 'clone', '--local', '--no-hardlinks', '--no-checkout', str(source), str(target)],
            logs, logs / (target.name + '-clone'))
    checked(['git', 'checkout', '--detach', revision], target, logs / (target.name + '-checkout'))
    if git(target, 'rev-parse', 'HEAD') != revision:
        raise ValueError('Checkout revision mismatch')
    if (target / '.ae').exists():
        raise ValueError('Source revision includes memory; refusing contaminated checkout')


def preparation_command(context, sessions, prompt):
    settings = arm_settings(context.args, 'ae')
    provider, model_id = settings.model.split('/', 1)
    return [context.args.pi, '--offline', '--provider', provider, '--model', model_id,
            '--thinking', settings.thinking, '--no-extensions', '--no-mcp', '--no-skills',
            '--no-prompt-templates', '--no-themes', '--no-context-files', '--no-approve',
            '--extension', str(context.args.ae_root / 'integrations/pi/extension.mjs'),
            '--tools', 'read,bash,' + AE_TOOLS, '--session-dir', str(sessions), '--print', '@' + str(prompt)]


def prepare_memory(context):
    """Run the real AE init workflow before TASK.md exists. Never manufacture journal rows."""
    args, settings = context.args, arm_settings(context.args, 'ae')
    workspace = context.workspaces / 'preparation'
    clone(context.source, workspace, context.spec.revision, context.logs)
    cli = ['node', str(args.ae_root / 'dist/cli.js')]
    checked(cli + ['prepare-prompt', '--project', str(workspace)], workspace,
            context.logs / 'preparation-prompt', 15)
    prompt = context.run / 'preparation-prompt.md'
    shutil.copyfile(context.logs / 'preparation-prompt.stdout', prompt)
    sessions = context.run / 'preparation-sessions'
    sessions.mkdir()
    stat = process(preparation_command(context, sessions, prompt), workspace,
                   context.logs / 'preparation-agent', args.preparation_timeout,
                   lambda: live_stop(sessions, args.preparation_max_calls, args.max_tool_errors))
    traces = list(sessions.glob('*.jsonl'))
    usage = result_mapping(analyze(traces[0], settings.model, settings.thinking, None)) if len(traces) == 1 else {'problems': ['missing_or_multiple_sessions']}
    problems = list(usage['problems'])
    if live_stop(sessions, args.preparation_max_calls + 1, args.max_tool_errors):
        problems.append('preparation_limit')
    if not succeeded(stat):
        problems.append('preparation_process_failed')
    problems += extension_problems(settings, (context.logs / 'preparation-agent.stderr').read_text())
    if git(workspace, 'rev-parse', 'HEAD') != context.spec.revision:
        problems.append('preparation_changed_head')
    files = snapshot_changes(workspace, context.run / 'preparation-source-changes', exclude_ticket=False)
    if files:
        problems.append('preparation_changed_source')
    prepared = {'model': settings.model, 'thinking': settings.thinking, 'agent': result_mapping(stat),
                'usage': usage, 'problems': problems, 'valid': False, 'cost_scope': 'preparation-only; excluded from repair totals',
                'coverage': 'agent-reported; requires review', 'files': files}
    context.record.preparation = prepared
    checked(cli + ['read', '--project', str(workspace)], workspace, context.logs / 'preparation-read', 30)
    recovered = json.loads((context.logs / 'preparation-read.stdout').read_text())
    state = recovered['state']
    if recovered['writerLockPresent']:
        problems.append('preparation_locked')
    if not state['statements'] or not any(e.get('revision') == context.spec.revision and e.get('kind') == 'file' for e in state['evidence']):
        problems.append('preparation_missing_anchored_findings')
    journal = workspace / '.ae/journal.ndjson'
    if journal.is_file():
        frozen = context.run / 'preparation-memory.ndjson'
        shutil.copyfile(journal, frozen)
        frozen.chmod(0o600)
        prepared['memory_sha256'] = sha(frozen)
    prepared['counts'] = {name: len(state[name]) for name in ('subjects', 'statements', 'evidence', 'relationships')}
    if ae_identity(args.ae_root) != context.record.ae_identity:
        problems.append('preparation_runtime_changed')
    prepared['valid'] = not problems
    dump(context.run / 'preparation-result.json', prepared)
    if not prepared['valid']:
        raise RuntimeError('AE initialization failed validation; no repair sessions launched')


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


@dataclass(frozen=True)
class SessionAnalysis:
    usage_events: int
    assistant_calls: int
    models: list[str]
    thinking_levels: list[str]
    tokens: dict[str, int]
    cost_components_usd: dict[str, float]
    total_tokens: int | None
    estimated_usd: float | None
    memory_messages: int
    context_characters: int
    reasoning_tokens: None
    problems: list[str]
    session_sha256: str

    def __getitem__(self, key):
        return getattr(self, key)


@dataclass(frozen=True)
class SessionEvents:
    models: list[str]
    thinking_levels: list[str]
    context: list[str]
    usage: list[object]
    assistant_calls: int
    problems: list[str]


def collect_session_events(events, model):
    models, levels, context, usage, problems = [], [], [], [], []
    assistant_calls = 0
    for event in events:
        if event.get('type') == 'model_change':
            models.append(event.get('provider', '') + '/' + event.get('modelId', ''))
        if event.get('type') == 'thinking_level_change':
            levels.append(event.get('thinkingLevel'))
        if event.get('customType') == 'ae-context':
            context.append(event.get('content', ''))
        message = event.get('message', {})
        if message.get('role') == 'assistant':
            if message.get('stopReason') in ('error', 'aborted', 'length'):
                problems.append('assistant_' + message['stopReason'])
            if message.get('usage') is not None:
                assistant_calls += 1
                usage.append(message['usage'])
                if message.get('provider', '') + '/' + message.get('model', '') != model:
                    problems.append('usage_model_mismatch')
        elif event.get('type') in ('usage', 'compaction', 'branch_summary'):
            raw = event.get('usage')
            if raw is not None:
                usage.append(raw)
    return SessionEvents(models, levels, context, usage, assistant_calls, problems)


def reconcile_usage(records):
    tokens = {key: 0 for key in TOKEN_FIELDS}
    costs = {key: 0.0 for key in TOKEN_FIELDS}
    total_tokens = total_cost = 0
    problems = []
    for raw in records:
        if not isinstance(raw, dict):
            problems.extend(['missing_or_invalid_token_metadata', 'missing_or_invalid_price_metadata'])
            continue
        if not all(number(raw.get(key)) for key in TOKEN_FIELDS + ('totalTokens',)):
            problems.append('missing_or_invalid_token_metadata')
        else:
            for key in TOKEN_FIELDS:
                tokens[key] += raw[key]
            total_tokens += raw['totalTokens']
            if raw['totalTokens'] != sum(raw[key] for key in TOKEN_FIELDS):
                problems.append('token_total_mismatch')
        cost = raw.get('cost')
        if not isinstance(cost, dict) or not all(number(cost.get(key)) for key in TOKEN_FIELDS + ('total',)):
            problems.append('missing_or_invalid_price_metadata')
            continue
        for key in TOKEN_FIELDS:
            costs[key] += cost[key]
        total_cost += cost['total']
        if not math.isclose(cost['total'], sum(cost[key] for key in TOKEN_FIELDS), abs_tol=1e-8):
            problems.append('cost_total_mismatch')
    return tokens, costs, total_tokens, total_cost, problems


def session_policy_problems(collected, model, thinking, expect_memory):
    problems = list(collected.problems)
    if not collected.assistant_calls:
        problems.append('no_billed_assistant_calls')
    if not collected.models or any(value != model for value in collected.models):
        problems.append('selected_model_mismatch')
    if not collected.thinking_levels or any(value != thinking for value in collected.thinking_levels):
        problems.append('effective_reasoning_mismatch')
    if expect_memory is not None and bool(collected.context) != expect_memory:
        problems.append('memory_treatment_mismatch')
    return problems


def analyze(path, model, thinking, expect_memory):
    events = read_events(path)
    if not events or events[0].get('type') != 'session':
        raise ValueError('Missing session header')
    collected = collect_session_events(events, model)
    tokens, costs, total_tokens, total_cost, accounting_problems = reconcile_usage(collected.usage)
    problems = sorted(set(session_policy_problems(collected, model, thinking, expect_memory) + accounting_problems))
    return SessionAnalysis(len(collected.usage), collected.assistant_calls, collected.models, collected.thinking_levels,
                           tokens, costs, None if any('token_' in problem for problem in problems) else total_tokens,
                           None if any('price_' in problem or 'cost_' in problem for problem in problems) else total_cost,
                           len(collected.context), sum(len(item) for item in collected.context), None, problems, sha(path))


def fixture_result(checkout, spec, inputs, logs, name, timeout):
    fixture_destination = spec.fixture_destination if isinstance(spec, CaseSpec) else spec['fixture_destination']
    package = spec.package if isinstance(spec, CaseSpec) else spec['package']
    tests = spec.tests if isinstance(spec, CaseSpec) else tuple(spec['tests'])
    target = checkout / fixture_destination
    if target.exists():
        raise ValueError('Acceptance fixture filename already exists')
    shutil.copy2(inputs / 'acceptance_test.go', target)
    result = process(['go', 'test', '-json', '-count=1', '-timeout=30s', package,
                      '-run', '^TestCaseStudy'], checkout, logs / name, timeout)
    terminal = {}
    text = (logs / (name + '.stdout')).read_text()
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('Test') in tests and event.get('Action') in ('pass', 'fail', 'skip'):
            terminal[event['Test']] = event['Action']
    ran = set(terminal) == set(tests) and all(value != 'skip' for value in terminal.values())
    return {**result_mapping(result), 'terminal_tests': terminal,
            'baseline_red': ran and result_value(result, 'exit_code') == 1 and result_value(result, 'stop_reason') is None
                            and 'CASE_STUDY_REGRESSION:' in text and 'panic:' not in text,
            'fixed_green': ran and all(value == 'pass' for value in terminal.values())
                           and succeeded(result)}


def snapshot_changes(workspace, destination, exclude_ticket=True):
    destination.mkdir()
    tracked = git(workspace, 'diff', 'HEAD', '--name-only', '-z').split('\0')
    untracked = git(workspace, 'ls-files', '--others', '--exclude-standard', '-z').split('\0')
    files = []
    for name in sorted(set(tracked + untracked) - {''}):
        if (exclude_ticket and name == 'TASK.md') or name.startswith('.ae/'):
            continue
        relative = safe_relative(name)
        path = workspace / relative
        if path.is_symlink() or not within(path, workspace):
            raise ValueError('Refusing a symlink or escaping path in candidate changes')
        if path.exists() and not path.is_file():
            raise ValueError('Candidate path is not a regular file')
        if path.is_file():
            if path.stat().st_size > 10 * 1024 * 1024:
                raise ValueError('Candidate file exceeds 10 MiB snapshot limit')
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        files.append({'path': name, 'sha256': sha(path) if path.exists() else None})
    return files


def apply_snapshot(snapshot, files, checkout):
    for entry in files:
        relative = safe_relative(entry['path'])
        target = checkout / relative
        if target.is_symlink() or not within(target, checkout):
            raise ValueError('Refusing a symlink or escaping evaluation path')
        if entry['sha256'] is None:
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(snapshot / relative, target)


def agent_command(args, arm, sessions, inputs):
    settings = arm_settings(args, arm)
    provider, model_id = settings.model.split('/', 1)
    command = [args.pi, '--offline', '--provider', provider, '--model', model_id,
               '--thinking', settings.thinking, '--no-extensions', '--no-mcp',
               '--no-skills', '--no-prompt-templates', '--no-themes', '--no-context-files',
               '--no-approve', '--append-system-prompt', str(inputs / 'instructions.md'),
               '--tools', 'read,bash,edit,write' + (',' + AE_TOOLS if settings.name == 'ae' else ''),
               '--session-dir', str(sessions), '--print', '@TASK.md']
    if settings.name == 'ae':
        command += ['--extension', str(args.ae_root / 'integrations/pi/extension.mjs')]
    return command


def frozen_inputs(run, case, spec):
    inputs = run / 'inputs'
    inputs.mkdir()
    for source, name in [(ROOT / 'bench.py', 'bench.py'), (ROOT / 'cases.json', 'cases.json'),
                         (ROOT / 'instructions.md', 'instructions.md'),
                         (ROOT / 'tickets' / (case + '.md'), 'TASK.md'),
                         (ROOT / 'acceptance' / (case + '_test.go'), 'acceptance_test.go')]:
        shutil.copy2(source, inputs / name)
    return inputs


def new_run(output, case, mode):
    if within(output, ROOT):
        raise ValueError('Keep subject workspaces and private artifacts outside this repository')
    output.mkdir(parents=True, exist_ok=True)
    run = output / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + case + '-' + mode + '-' + uuid4().hex[:8])
    run.mkdir(mode=0o700)
    (run / 'logs').mkdir()
    (run / 'workspaces').mkdir()
    return run


def ae_identity(ae_root):
    cli = ae_root / 'dist/cli.js'
    extension = ae_root / 'integrations/pi/extension.mjs'
    if not cli.is_file() or not extension.is_file():
        raise ValueError('Built AE checkout required (dist/cli.js and Pi extension)')
    paths = [path for base in ('src', 'dist', 'integrations/pi', 'prompts') for path in (ae_root / base).rglob('*')
             if path.is_file() and path.suffix in ('.ts', '.js', '.mjs', '.md')]
    paths.append(ae_root / 'package.json')
    if not (ae_root / 'prompts/init.md').is_file():
        raise ValueError('AE initialization prompt missing from package')
    return {'head': git(ae_root, 'rev-parse', 'HEAD') if (ae_root / '.git').exists() else None,
            'status': git(ae_root, 'status', '--short') if (ae_root / '.git').exists() else 'installed package',
            'runtime_files': {str(path.relative_to(ae_root)): sha(path) for path in sorted(paths)}}


@dataclass(frozen=True)
class ArmResult:
    settings: ArmSettings
    agent: ProcessResult
    usage: SessionAnalysis | dict
    problems: list[str]
    files: list[dict]
    modified: bool
    regression: dict
    package: ProcessResult
    race: ProcessResult | None
    repair_verified: bool
    valid: bool

    def to_dict(self):
        return {'model': self.settings.model, 'thinking': self.settings.thinking,
                'agent': result_mapping(self.agent), 'usage': result_mapping(self.usage),
                'problems': self.problems, 'files': self.files, 'modified': self.modified,
                'regression': self.regression, 'package': result_mapping(self.package),
                'race': result_mapping(self.race) if self.race else None,
                'repair_verified': self.repair_verified, 'valid': self.valid}


@dataclass
class RunRecord:
    case: str
    mode: str
    source: str
    revision: str
    created_utc: str
    input_sha256: dict[str, str]
    limits: dict[str, object]
    canonical_eligible: bool = False
    requested: dict | None = None
    race_enabled: bool | None = None
    ae_identity: dict | None = None
    go_version: str | None = None
    pi_version: str | None = None
    baseline: dict | None = None
    preparation: dict | None = None
    fixed_revision: str | None = None
    fixed: dict | None = None
    order: list[str] | None = None
    arms: dict[str, ArmResult] = field(default_factory=dict)
    ae_unchanged: bool | None = None
    check_passed: bool = False
    error: dict | None = None
    interrupted: bool = False
    evidence_sha256: dict[str, str] | None = None

    def to_dict(self):
        data = {key: value for key, value in json_value(self).items() if value is not None}
        data['arms'] = {name: arm.to_dict() for name, arm in self.arms.items()}
        if not self.check_passed:
            data.pop('check_passed')
        if not self.interrupted:
            data.pop('interrupted')
        return data


@dataclass(frozen=True)
class RunContext:
    args: argparse.Namespace
    case: str
    spec: CaseSpec
    source: Path
    run: Path
    logs: Path
    workspaces: Path
    inputs: Path
    record: RunRecord


@dataclass(frozen=True)
class AgentInspection:
    usage: SessionAnalysis | dict
    problems: list[str]


@dataclass(frozen=True)
class ArmAttempt:
    workspace: Path
    sessions: Path
    stat: ProcessResult
    files: list[dict]
    inspection: AgentInspection


def report(run, result):
    lines = [f"# {result['case']} benchmark candidate", '',
             'Canonical only after explicit selection. Table costs/times cover repair only; preparation is retained separately and excluded.', '',
             '| Arm | Requested model / reasoning | Agent seconds | Calls | Tokens | Estimated USD | Repair verified | Valid treatment |',
             '|---|---|---:|---:|---:|---:|---|---|']
    for arm, item in result.get('arms', {}).items():
        usage = item.get('usage', {})
        lines.append(f"| {arm} | {item['model']} / {item['thinking']} | {item['agent']['seconds']} | "
                     f"{usage.get('assistant_calls', 'unknown')} | {usage.get('total_tokens', 'unknown')} | "
                     f"{usage.get('estimated_usd', 'unknown')} | {item['repair_verified']} | {item['valid']} |")
    lines += ['', '## Boundaries', '',
              '- Read results.json and test JSON logs for exact failures, model settings and treatment warnings.',
              '- Shared acceptance tests are frozen evaluator tests derived from known regressions, not hidden production incidents.',
              '- Different models/reasoning are allowed and reported; those comparisons do not isolate memory.',
              '- AE runs real project-memory preparation before ticket exposure; source-derived knowledge is not invented past session history.',
              '- Preparation validity checks process/provenance plumbing, not comprehensive understanding; review its coverage and recorded claims.',
              '- Separate sessions/checkouts and prompt boundaries are not a security sandbox; caches remain shared.',
              '- Candidate evaluation is outside measured agent time; failed candidate runs remain private protocol evidence.',
              '- Raw logs/patches may contain sensitive data; do not publish without review.',
              '', f"Canonical eligible: {result.get('canonical_eligible', False)}", '']
    if result.get('preparation'):
        prep = result['preparation']
        lines += ['## Preparation (excluded from repair totals)', '',
                  f"Model/reasoning: {prep['model']} / {prep['thinking']}; seconds: {prep['agent']['seconds']}; "
                  f"calls: {prep['usage'].get('assistant_calls', 'unknown')}; estimated USD: {prep['usage'].get('estimated_usd', 'unknown')}.",
                  f"Valid execution: {prep['valid']}. Review preparation-memory.ndjson and the preparation session for coverage/gaps.", '']
    (run / 'report.md').write_text('\n'.join(lines))


def prepare_run(args, case, source):
    spec = load_case(case)
    source = source.resolve()
    git(source, 'cat-file', '-e', spec.revision + '^{commit}')
    if within(args.output, source) or within(source, args.output):
        raise ValueError('Source and output must not contain one another')
    run = new_run(args.output, case, args.command)
    print(f'{case}: {run}', flush=True)
    inputs = frozen_inputs(run, case, spec)
    record = RunRecord(case, args.command, str(source), spec.revision, datetime.now(timezone.utc).isoformat(),
                       {path.name: sha(path) for path in inputs.iterdir()},
                       {key: getattr(args, key) for key in ('test_timeout', 'agent_timeout', 'max_calls', 'max_tool_errors', 'preparation_timeout', 'preparation_max_calls') if hasattr(args, key)})
    if args.command == 'run':
        record.requested = {arm: {'model': getattr(args, arm + '_model'),
                                  'thinking': getattr(args, arm + '_thinking')} for arm in ('control', 'ae')}
        record.race_enabled = args.race
    return RunContext(args, case, spec, source, run, run / 'logs', run / 'workspaces', inputs, record)


def collect_environment(context):
    args, record = context.args, context.record
    if args.ae_root:
        record.ae_identity = ae_identity(args.ae_root)
    if args.command != 'prepare':
        record.go_version = subprocess.check_output(['go', 'version'], timeout=15, text=True).strip()
    if args.command in ('run', 'prepare'):
        record.pi_version = subprocess.check_output([args.pi, '--version'], timeout=15, text=True).strip()


def prove_baseline(context):
    baseline = context.workspaces / 'baseline'
    clone(context.source, baseline, context.spec.revision, context.logs)
    context.record.baseline = fixture_result(baseline, context.spec, context.inputs, context.logs,
                                             'baseline-regression', context.args.test_timeout)
    if not context.record.baseline['baseline_red']:
        raise RuntimeError('Expected assertion-level baseline failure was not established; no models launched')


def run_check(context):
    args, spec, record = context.args, context.spec, context.record
    if args.ae_root:
        workspace = context.workspaces / 'ae-read-check'
        clone(context.source, workspace, spec.revision, context.logs)
        checked(['node', str(args.ae_root / 'dist/cli.js'), 'prepare-prompt', '--project', str(workspace)],
                workspace, context.logs / 'preparation-prompt-check', 15)
        if (workspace / '.ae').exists():
            raise RuntimeError('Read-only initialization prompt construction created a store')
    if args.fixed_source:
        fixed = context.workspaces / 'fixed'
        record.fixed_revision = git(args.fixed_source, 'rev-parse', 'HEAD')
        clone(args.fixed_source, fixed, record.fixed_revision, context.logs)
        record.fixed = fixture_result(fixed, spec, context.inputs, context.logs, 'fixed-regression', args.test_timeout)
        if not record.fixed['fixed_green']:
            raise RuntimeError('Reference fix failed the shared regression')
    record.check_passed = True


def invariant_problems(context, workspace, sessions):
    problems = []
    final_stop = live_stop(sessions, context.args.max_calls + 1, context.args.max_tool_errors)
    if final_stop:
        problems.append(final_stop)
    if git(workspace, 'rev-parse', 'HEAD') != context.spec.revision:
        problems.append('agent_changed_head')
    if sha(workspace / 'TASK.md') != sha(context.inputs / 'TASK.md'):
        problems.append('agent_changed_ticket')
    return problems


def session_usage(settings, traces):
    if len(traces) != 1:
        return {'problems': ['missing_or_multiple_sessions']}
    return analyze(traces[0], settings.model, settings.thinking, settings.name == 'ae')


def extension_problems(settings, stderr):
    if settings.name == 'ae' and any(value in stderr for value in ('Æ automatic handoff unavailable', 'Æ context unavailable')):
        return ['ae_extension_failure']
    return []


def inspect_agent_attempt(context, settings, workspace, sessions):
    traces = list(sessions.glob('*.jsonl'))
    problems = invariant_problems(context, workspace, sessions)
    problems += extension_problems(settings, (context.logs / (settings.name + '-agent.stderr')).read_text())
    return AgentInspection(session_usage(settings, traces), problems)


def collect_arm_attempt(context, settings):
    workspace = context.workspaces / settings.name
    clone(context.source, workspace, context.spec.revision, context.logs)
    shutil.copy2(context.inputs / 'TASK.md', workspace / 'TASK.md')
    if settings.name == 'ae':
        if not context.record.preparation or not context.record.preparation['valid']:
            raise RuntimeError('Validated project-memory preparation required before repair')
        memory = context.run / 'preparation-memory.ndjson'
        if sha(memory) != context.record.preparation['memory_sha256']:
            raise RuntimeError('Prepared memory changed before repair')
        (workspace / '.ae').mkdir(mode=0o700)
        shutil.copyfile(memory, workspace / '.ae/journal.ndjson')
        (workspace / '.ae/journal.ndjson').chmod(0o600)
    sessions = context.run / (settings.name + '-sessions')
    sessions.mkdir()
    stat = process(agent_command(context.args, settings.name, sessions, context.inputs), workspace,
                   context.logs / (settings.name + '-agent'), context.args.agent_timeout,
                   lambda: live_stop(sessions, context.args.max_calls, context.args.max_tool_errors))
    files = snapshot_changes(workspace, context.run / (settings.name + '-changes'))
    dump(context.run / (settings.name + '-files.json'), files)
    inspection = inspect_agent_attempt(context, settings, workspace, sessions)
    if settings.name == 'ae':
        shutil.copy2(workspace / '.ae/journal.ndjson', context.run / 'memory-after-repair.ndjson')
    return ArmAttempt(workspace, sessions, stat, files, inspection)


def evaluate_arm(context, settings, attempt):
    evaluation = context.workspaces / (settings.name + '-evaluation')
    clone(context.source, evaluation, context.spec.revision, context.logs)
    apply_snapshot(context.run / (settings.name + '-changes'), attempt.files, evaluation)
    green = fixture_result(evaluation, context.spec, context.inputs, context.logs,
                           settings.name + '-regression', context.args.test_timeout)
    package = process(['go', 'test', '-count=1', '-timeout=90s', context.spec.packages],
                      evaluation, context.logs / (settings.name + '-packages'), context.args.test_timeout)
    race = process(['go', 'test', '-race', '-count=1', '-timeout=90s', context.spec.packages],
                   evaluation, context.logs / (settings.name + '-race'), context.args.test_timeout) if context.args.race else None
    modified = any(entry['path'].startswith(context.spec.implementation_prefix) and entry['path'].endswith('.go')
                   and not entry['path'].endswith('_test.go') for entry in attempt.files)
    repair = modified and green['fixed_green'] and succeeded(package) and (race is None or succeeded(race))
    return green, package, race, modified, repair


def run_arm(context, settings):
    attempt = collect_arm_attempt(context, settings)
    green, package, race, modified, repair = evaluate_arm(context, settings, attempt)
    usage = result_mapping(attempt.inspection.usage)
    valid = succeeded(attempt.stat) and not attempt.inspection.problems and not usage['problems']
    arm_result = ArmResult(settings, attempt.stat, attempt.inspection.usage, attempt.inspection.problems,
                           attempt.files, modified, green, package, race, repair, valid)
    context.record.arms[settings.name] = arm_result
    dump(context.run / (settings.name + '-result.json'), arm_result.to_dict())
    print(f'{settings.name}: repair_verified={repair}, valid={valid}', flush=True)


def run_candidate(context):
    prepare_memory(context)
    context.record.order = context.args.order.split(',')
    for name in context.record.order:
        run_arm(context, arm_settings(context.args, name))
    context.record.ae_unchanged = ae_identity(context.args.ae_root) == context.record.ae_identity
    context.record.canonical_eligible = context.record.ae_unchanged and all(
        arm.repair_verified and arm.valid for arm in context.record.arms.values())


def finalize_run(context):
    record = context.record
    record.evidence_sha256 = {str(path.relative_to(context.run)): sha(path) for path in sorted(context.run.rglob('*'))
                              if path.is_file() and path.relative_to(context.run).parts[0] != 'workspaces'}
    result = record.to_dict()
    dump(context.run / 'results.json', result)
    report(context.run, result)


def execute(args, case, source):
    context = prepare_run(args, case, source)
    try:
        collect_environment(context)
        if args.command != 'prepare':
            prove_baseline(context)
        if args.command == 'prepare':
            prepare_memory(context)
        elif args.command == 'check':
            run_check(context)
        else:
            run_candidate(context)
    except BaseException as error:
        context.record.error = {'type': type(error).__name__, 'message': str(error) if isinstance(error, (ValueError, RuntimeError)) else 'Local operation interrupted or failed; inspect private logs'}
        if isinstance(error, KeyboardInterrupt):
            context.record.interrupted = True
    finally:
        finalize_run(context)
    if args.command == 'prepare':
        return bool(context.record.preparation and context.record.preparation['valid'] and not context.record.error)
    return context.record.check_passed if args.command == 'check' else context.record.canonical_eligible


def select(run, output):
    result_path = run / 'results.json'
    data = json.loads(result_path.read_text())
    if data.get('mode') != 'run' or not data.get('canonical_eligible') or set(data.get('arms', {})) != {'control', 'ae'}:
        raise ValueError('Only completed, validated pairs can be selected')
    for name, expected in data['input_sha256'].items():
        if sha(run / 'inputs' / name) != expected:
            raise ValueError('Run inputs changed since execution')
    for name, expected in data['evidence_sha256'].items():
        if sha(run / name) != expected:
            raise ValueError('Run evidence changed since execution')
    if within(output, ROOT):
        raise ValueError('Keep canonical evidence outside this repository')
    output.mkdir(parents=True, exist_ok=True)
    # Append rather than overwrite prior designations. The last entry per case is current.
    entry = {'case': data['case'], 'run': str(run.resolve()), 'results_sha256': sha(result_path),
             'selected_utc': datetime.now(timezone.utc).isoformat()}
    with (output / 'canonical.ndjson').open('a') as stream:
        stream.write(json.dumps(entry) + '\n')
    print(json.dumps(entry, indent=2))


def parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    default_output = Path.home() / '.local/state/ae_case_studies'
    for command in ('run', 'check', 'prepare'):
        current = sub.add_parser(command)
        current.add_argument('case', choices=('caddy', 'restic', 'rclone', 'all'))
        current.add_argument('--source', type=Path, help='Existing local clone for a single case; never modified')
        current.add_argument('--source-root', type=Path, help='Parent of caddy/restic/rclone clones for all cases')
        current.add_argument('--output', type=Path, default=default_output)
        current.add_argument('--ae-root', type=Path, required=command in ('run', 'prepare'))
        current.add_argument('--test-timeout', type=float, default=120)
        if command == 'check':
            current.add_argument('--fixed-source', type=Path, help='Optional committed reference fix (single case only)')
        if command in ('run', 'prepare'):
            current.add_argument('--preparation-timeout', type=float, default=1200)
            current.add_argument('--preparation-max-calls', type=int, default=100)
            current.add_argument('--ae-model', required=True, help='Exact provider/model ID')
            current.add_argument('--ae-thinking', choices=THINKING, default='high')
            current.add_argument('--max-tool-errors', type=int, default=4)
            current.add_argument('--pi', default='pi')
        if command == 'run':
            current.add_argument('--control-model', required=True, help='Exact provider/model ID')
            current.add_argument('--control-thinking', choices=THINKING, default='high')
            current.add_argument('--agent-timeout', type=float, default=420)
            current.add_argument('--max-calls', type=int, default=35)
            current.add_argument('--order', choices=('control,ae', 'ae,control'), default='control,ae')
            current.add_argument('--race', action=argparse.BooleanOptionalAction, default=True)
    current = sub.add_parser('select', help='Explicitly designate a completed pair canonical, without publishing it')
    current.add_argument('run', type=Path)
    current.add_argument('--output', type=Path, default=default_output)
    return parser


def main():
    os.umask(0o077)
    args = parser().parse_args()
    try:
        if args.command == 'select':
            select(args.run.resolve(), args.output.resolve())
            return 0
        args.output = args.output.resolve()
        if args.ae_root:
            args.ae_root = args.ae_root.resolve()
        if args.case == 'all':
            if not args.source_root or args.source or getattr(args, 'fixed_source', None):
                parser().error('all requires --source-root and forbids --source/--fixed-source')
        elif not args.source or args.source_root:
            parser().error('a single case requires --source, not --source-root')
        for flag in ('test_timeout', 'agent_timeout', 'max_calls', 'max_tool_errors', 'preparation_timeout', 'preparation_max_calls'):
            if hasattr(args, flag) and (not math.isfinite(getattr(args, flag)) or getattr(args, flag) <= 0):
                parser().error('limits must be positive finite numbers')
        if args.command in ('run', 'prepare'):
            for model in ([args.control_model, args.ae_model] if args.command == 'run' else [args.ae_model]):
                if (not re.fullmatch(r'[A-Za-z0-9_.-]+/[^\s]+', model)
                        or any(model.endswith(':' + level) for level in THINKING)):
                    parser().error('model must be provider/exact-model-id; use separate thinking options')
        cases = ('caddy', 'restic', 'rclone') if args.case == 'all' else (args.case,)
        for case in cases:
            if not execute(args, case, args.source_root / case if args.case == 'all' else args.source):
                return 1  # Do not launch more paid runs after a failed/invalid pair.
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f'Benchmark stopped: {type(error).__name__}; inspect configuration/private logs.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
