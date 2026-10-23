import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import bench


def usage():
    return {'input': 10, 'output': 2, 'cacheRead': 100, 'cacheWrite': 0, 'totalTokens': 112,
            'cost': {'input': .02, 'output': .02, 'cacheRead': .01, 'cacheWrite': 0, 'total': .05}}


def events(memory=False):
    data = [{'type': 'session', 'id': 'fixture'},
            {'type': 'model_change', 'provider': 'fixture', 'modelId': 'model'},
            {'type': 'thinking_level_change', 'thinkingLevel': 'high'}]
    if memory:
        data.append({'type': 'custom_message', 'customType': 'ae-context', 'content': 'Layout context'})
    data.append({'type': 'message', 'message': {'role': 'assistant', 'provider': 'fixture', 'model': 'model',
                                              'usage': usage(), 'content': []}})
    return data


def write_events(path, data):
    path.write_text(''.join(json.dumps(e) + '\n' for e in data))


class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'session.jsonl'

    def analyze(self, data, memory=False):
        write_events(self.path, data)
        return bench.analyze(self.path, 'fixture/model', 'high', memory)

    def test_reported_components_reconcile(self):
        result = self.analyze(events())
        self.assertEqual(result['problems'], [])
        self.assertEqual(result['total_tokens'], 112)
        self.assertEqual(result['estimated_usd'], .05)
        self.assertIsNone(result['reasoning_tokens'])

    def test_missing_prices_are_unknown_not_zero(self):
        data = events()
        del data[-1]['message']['usage']['cost']
        result = self.analyze(data)
        self.assertIsNone(result['estimated_usd'])
        self.assertIn('missing_or_invalid_price_metadata', result['problems'])

    def test_missing_tokens_do_not_erase_known_cost(self):
        data = events()
        del data[-1]['message']['usage']['output']
        result = self.analyze(data)
        self.assertIsNone(result['total_tokens'])
        self.assertEqual(result['estimated_usd'], .05)

    def test_effective_model_and_reasoning_are_checked(self):
        data = events()
        data[1]['modelId'] = 'other'
        data[2]['thinkingLevel'] = 'medium'
        result = self.analyze(data)
        self.assertIn('selected_model_mismatch', result['problems'])
        self.assertIn('effective_reasoning_mismatch', result['problems'])

    def test_memory_required_only_for_treatment(self):
        self.assertIn('memory_treatment_mismatch', self.analyze(events(), True)['problems'])
        self.assertIn('memory_treatment_mismatch', self.analyze(events(True))['problems'])
        self.assertEqual(self.analyze(events(True), True)['problems'], [])

    def test_provider_failure_invalidates_normal_process_exit(self):
        data = events()
        data[-1]['message']['stopReason'] = 'error'
        self.assertIn('assistant_error', self.analyze(data)['problems'])

    def test_compaction_charges_are_not_silently_dropped(self):
        data = events() + [{'type': 'compaction', 'usage': usage()}]
        result = self.analyze(data)
        self.assertEqual(result['usage_events'], 2)
        self.assertEqual(result['assistant_calls'], 1)
        self.assertEqual(result['total_tokens'], 224)
        self.assertAlmostEqual(result['estimated_usd'], .1)

    def test_corrupt_finished_session_is_rejected(self):
        self.path.write_text('{bad json}\n')
        with self.assertRaises(ValueError):
            bench.analyze(self.path, 'fixture/model', 'high', False)

    def test_error_limit_is_latched_even_after_later_success(self):
        data = events() + [{'type': 'message', 'message': {'role': 'toolResult', 'isError': True}}] * 4
        data.append({'type': 'message', 'message': {'role': 'toolResult', 'isError': False}})
        write_events(self.path, data)
        self.assertEqual(bench.live_stop(self.path.parent, 35, 4), 'tool_error_limit')

    def test_incomplete_live_tail_is_not_a_corrupt_session(self):
        write_events(self.path, events())
        with self.path.open('a') as stream:
            stream.write('{incomplete')
        self.assertIsNone(bench.live_stop(self.path.parent, 35, 4))
        with self.assertRaises(ValueError):
            bench.read_events(self.path)


class SafetyTests(unittest.TestCase):
    def test_preparation_uses_real_init_prompt_without_repair_instructions_or_edit_tools(self):
        args = bench.parser().parse_args(['prepare', 'caddy', '--source', '/source',
                                         '--ae-root', '/installed', '--ae-model', 'fixture/model'])
        context = argparse.Namespace(args=args)
        command = bench.preparation_command(context, Path('/sessions'), Path('/preparation-prompt.md'))
        self.assertEqual(command[-1], '@/preparation-prompt.md')
        self.assertNotIn('--append-system-prompt', command)
        tools = command[command.index('--tools') + 1].split(',')
        self.assertNotIn('edit', tools)
        self.assertNotIn('write', tools)
        self.assertIn('ae_record', tools)
        self.assertNotIn('TASK.md', command)

    def test_output_inside_benchmark_repository_is_rejected(self):
        with self.assertRaises(ValueError):
            bench.new_run(bench.ROOT / 'runs', 'restic', 'run')

    def test_existing_workspace_is_never_reset(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            marker = target / 'user-work'
            marker.write_text('preserve me')
            with self.assertRaises(ValueError):
                bench.clone(target, target, 'unneeded', target)
            self.assertEqual(marker.read_text(), 'preserve me')

    def test_snapshot_includes_untracked_tests_and_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source'
            source.mkdir()
            subprocess.run(['git', 'init', '-q', str(source)], check=True)
            # An empty tree needs a HEAD for git diff, but no user repository is committed.
            tree = subprocess.check_output(['git', '-C', str(source), 'mktree'], input=b'').strip()
            env = dict(os.environ, GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@example.invalid',
                       GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@example.invalid')
            commit = subprocess.check_output(['git', '-C', str(source), 'commit-tree', tree.decode()],
                                             input=b'test fixture\n', env=env).decode().strip()
            subprocess.run(['git', '-C', str(source), 'update-ref', 'HEAD', commit], check=True)
            (source / 'new_test.go').write_text('package fixture\n')
            result = bench.snapshot_changes(source, root / 'snapshot')
            self.assertEqual([f['path'] for f in result], ['new_test.go'])
            (source / 'escape.go').symlink_to(root / 'outside')
            with self.assertRaises(ValueError):
                bench.snapshot_changes(source, root / 'bad-snapshot')

    def test_different_models_and_thinking_are_explicit_cli_choices(self):
        args = bench.parser().parse_args(['run', 'caddy', '--source', '/source', '--ae-root', '/ae',
                                         '--control-model', 'fixture/sol', '--ae-model', 'fixture/luna',
                                         '--control-thinking', 'high', '--ae-thinking', 'medium'])
        settings = bench.arm_settings(args, 'ae')
        command = bench.agent_command(args, 'ae', Path('/sessions'), Path('/inputs'))
        self.assertEqual(settings, bench.ArmSettings('ae', 'fixture/luna', 'medium'))
        self.assertIn('luna', command)
        self.assertEqual(command[command.index('--thinking') + 1], 'medium')
        self.assertIn('--no-context-files', command)

    def test_arm_result_serialization_preserves_artifact_schema(self):
        process = bench.ProcessResult(['fixture'], '/fixture', 0, None, .1)
        result = bench.ArmResult(bench.ArmSettings('control', 'fixture/sol', 'high'), process,
                                 {'problems': []}, [], [], True, {'fixed_green': True}, process,
                                 None, True, True).to_dict()
        self.assertEqual(set(result), {'model', 'thinking', 'agent', 'usage', 'problems', 'files',
                                       'modified', 'regression', 'package', 'race',
                                       'repair_verified', 'valid'})
        self.assertEqual(result['model'], 'fixture/sol')
        self.assertEqual(result['agent']['exit_code'], 0)
        self.assertIsNone(result['race'])

    def test_extension_failure_classification_is_arm_specific(self):
        warning = 'Æ automatic handoff unavailable'
        self.assertEqual(bench.extension_problems(bench.ArmSettings('ae', 'fixture/model', 'high'), warning),
                         ['ae_extension_failure'])
        self.assertEqual(bench.extension_problems(bench.ArmSettings('control', 'fixture/model', 'high'), warning), [])
        self.assertEqual(bench.extension_problems(bench.ArmSettings('ae', 'fixture/model', 'high'), 'healthy'), [])

    def test_invalid_candidate_cannot_be_selected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bench.dump(root / 'results.json', {'mode': 'run', 'canonical_eligible': False})
            with self.assertRaises(ValueError):
                bench.select(root, root / 'registry')
            self.assertFalse((root / 'registry').exists())

    def test_changed_evidence_cannot_be_selected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            artifact = root / 'session.jsonl'
            artifact.write_text('original evidence')
            bench.dump(root / 'results.json', {'mode': 'run', 'case': 'restic', 'canonical_eligible': True,
                       'arms': {'control': {}, 'ae': {}}, 'input_sha256': {},
                       'evidence_sha256': {'session.jsonl': bench.sha(artifact)}})
            artifact.write_text('changed evidence')
            with self.assertRaises(ValueError):
                bench.select(root, root / 'registry')
            self.assertFalse((root / 'registry').exists())

    def test_baseline_requires_executed_assertion_failure(self):
        examples = [
            ('fail', 'CASE_STUDY_REGRESSION: missing bytes', True),
            ('fail', 'build failed', False),
            ('skip', 'CASE_STUDY_REGRESSION: skipped', False),
            ('pass', 'no failure', False),
        ]
        for action, text, expected in examples:
            with self.subTest(action=action, text=text), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root / 'acceptance_test.go').write_text('fixture')
                checkout = root / 'checkout'
                checkout.mkdir()
                spec = {'fixture_destination': 'zz_test.go', 'package': './', 'tests': ['TestCaseStudyFixture']}

                def fake_process(command, cwd, log, timeout):
                    log.with_suffix('.stdout').write_text(json.dumps({'Action': action,
                        'Test': 'TestCaseStudyFixture', 'Output': text}) + '\n')
                    return {'exit_code': 1, 'stop_reason': None}

                with mock.patch.object(bench, 'process', fake_process):
                    result = bench.fixture_result(checkout, spec, root, root, 'test-log', 5)
                self.assertEqual(result['baseline_red'], expected)

    def test_timeout_owns_process_termination(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = bench.process([sys.executable, '-c', 'import time; time.sleep(30)'],
                                   root, root / 'timeout', .1)
            self.assertEqual(result['stop_reason'], 'timeout')
            self.assertNotEqual(result['exit_code'], 0)


class ProcessIntegrationTests(unittest.TestCase):
    """Real subprocesses/Git fixtures, fake model and Go boundary. No hosted calls."""

    def test_complete_pair_is_verified_and_can_be_selected(self):
        self.run_pair(False)

    def test_handoff_failure_preserves_results_but_blocks_canonical_selection(self):
        self.run_pair(True)

    def test_preparation_source_changes_prevent_both_repair_runs_without_resetting_the_source(self):
        self.run_pair(False, preparation_failure=True)

    def test_check_validates_init_prompt_without_models_or_store_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, harness, tools = root / 'source', root / 'harness', root / 'tools'
            for path in (source, harness, tools, harness / 'tickets', harness / 'acceptance',
                         root / 'ae/dist', root / 'ae/integrations/pi'):
                path.mkdir(parents=True, exist_ok=True)
            subprocess.run(['git', 'init', '-q', str(source)], check=True)
            (source / 'demo.go').write_text('baseline\n')
            subprocess.run(['git', '-C', str(source), 'add', 'demo.go'], check=True)
            env = dict(os.environ, GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@example.invalid',
                       GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@example.invalid')
            tree = subprocess.check_output(['git', '-C', str(source), 'write-tree']).decode().strip()
            revision = subprocess.check_output(['git', '-C', str(source), 'commit-tree', tree],
                                               input=b'test fixture\n', env=env).decode().strip()
            subprocess.run(['git', '-C', str(source), 'update-ref', 'HEAD', revision], check=True)
            spec = {'revision': revision, 'seed': [{'id': 'layout', 'name': 'Layout', 'file': 'demo.go', 'text': 'Layout context'}],
                    'excluded_seed_terms': ['forbidden'], 'package': './', 'packages': './...',
                    'implementation_prefix': 'demo', 'fixture_destination': 'zz_case_study_acceptance_test.go',
                    'tests': ['TestCaseStudyFixture']}
            bench.dump(harness / 'cases.json', {'caddy': spec})
            for path in [harness / 'bench.py', harness / 'instructions.md',
                         harness / 'tickets/caddy.md', harness / 'acceptance/caddy_test.go',
                         root / 'ae/dist/cli.js', root / 'ae/integrations/pi/extension.mjs']:
                path.write_text('fixture\n')
            (tools / 'go').write_text('''#!/usr/bin/env python3
import json,sys
if 'version' in sys.argv:
    print('go version fixture'); sys.exit(0)
if '-json' in sys.argv:
    print(json.dumps({'Action':'output','Test':'TestCaseStudyFixture','Output':'CASE_STUDY_REGRESSION: baseline'}))
    print(json.dumps({'Action':'fail','Test':'TestCaseStudyFixture'}))
sys.exit(1)
''')
            (tools / 'node').write_text('''#!/usr/bin/env python3
import sys
from pathlib import Path
args=sys.argv
project=Path(args[args.index('--project')+1])
command=args[2]
if command == 'prepare-prompt':
    print('fixture preparation prompt')
else:
    raise SystemExit(2)
''')
            for path in (tools / 'go', tools / 'node'):
                path.chmod(0o700)
            args = argparse.Namespace(command='check', ae_root=root / 'ae', output=root / 'output',
                                      test_timeout=5, fixed_source=None)
            with mock.patch.object(bench, 'ROOT', harness), \
                    mock.patch.object(bench, 'ae_identity', return_value={'head': 'fixture'}), \
                    mock.patch.dict(os.environ, {'PATH': str(tools) + os.pathsep + os.environ['PATH']}), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(bench.execute(args, 'caddy', source))
            run = next(args.output.iterdir())
            result = json.loads((run / 'results.json').read_text())
            self.assertTrue(result['check_passed'])
            self.assertTrue(result['baseline']['baseline_red'])
            self.assertNotIn('preparation', result)
            self.assertFalse((run / 'workspaces/ae-read-check/.ae').exists())
            self.assertNotIn('error', result)
            self.assertTrue((run / 'logs/preparation-prompt-check.json').is_file())
            self.assertTrue((run / 'report.md').is_file())
            self.assertIn('logs/preparation-prompt-check.json', result['evidence_sha256'])

    def run_pair(self, handoff_failure, preparation_failure=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, harness, tools = root / 'source', root / 'harness', root / 'tools'
            for path in (source, harness, tools, harness / 'tickets', harness / 'acceptance'):
                path.mkdir()
            subprocess.run(['git', 'init', '-q', str(source)], check=True)
            (source / 'demo.go').write_text('baseline\n')
            subprocess.run(['git', '-C', str(source), 'add', 'demo.go'], check=True)
            env = dict(os.environ, GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@example.invalid',
                       GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@example.invalid')
            tree = subprocess.check_output(['git', '-C', str(source), 'write-tree']).decode().strip()
            revision = subprocess.check_output(['git', '-C', str(source), 'commit-tree', tree],
                                               input=b'test fixture\n', env=env).decode().strip()
            subprocess.run(['git', '-C', str(source), 'update-ref', 'HEAD', revision], check=True)
            spec = {'revision': revision, 'seed': [{'id': 'layout', 'text': 'Layout context'}], 'excluded_seed_terms': ['forbidden'],
                    'package': './', 'packages': './...', 'implementation_prefix': 'demo',
                    'fixture_destination': 'zz_case_study_acceptance_test.go', 'tests': ['TestCaseStudyFixture']}
            bench.dump(harness / 'cases.json', {'caddy': spec})
            for path in [harness / 'bench.py', harness / 'instructions.md',
                         harness / 'tickets/caddy.md', harness / 'acceptance/caddy_test.go']:
                path.write_text('fixture\n')
            go = tools / 'go'
            go.write_text('''#!/usr/bin/env python3
import json,sys
from pathlib import Path
if 'version' in sys.argv:
    print('go version fixture'); sys.exit(0)
fixed = Path('demo.go').read_text() == 'fixed\\n'
if '-json' in sys.argv:
    if not fixed:
        print(json.dumps({'Action':'output','Test':'TestCaseStudyFixture','Output':'CASE_STUDY_REGRESSION: baseline'}))
    print(json.dumps({'Action':'pass' if fixed else 'fail','Test':'TestCaseStudyFixture'}))
else:
    print('ok fixture')
sys.exit(0 if fixed else 1)
''')
            pi = tools / 'pi'
            pi.write_text('''#!/usr/bin/env python3
import json,sys
from pathlib import Path
if '--version' in sys.argv:
    print('pi fixture'); sys.exit(0)
a=sys.argv
value=lambda key:a[a.index(key)+1]
preparing = any(value.startswith('@') and value != '@TASK.md' for value in a)
if preparing:
    assert not Path('TASK.md').exists()
    assert not Path('zz_case_study_acceptance_test.go').exists()
    assert '--append-system-prompt' not in a
    Path('.ae').mkdir()
    Path('.ae/journal.ndjson').write_text('fixture\\n')
else:
    Path('demo.go').write_text('fixed\\n')
e=[{'type':'session','id':'fixture'},
   {'type':'model_change','provider':value('--provider'),'modelId':value('--model')},
   {'type':'thinking_level_change','thinkingLevel':value('--thinking')}]
if '--extension' in a and not preparing:
    e.append({'type':'custom_message','customType':'ae-context','content':'Layout context'})
e.append({'type':'message','message':{'role':'assistant','provider':value('--provider'),'model':value('--model'),
    'usage':{'input':1,'output':1,'cacheRead':0,'cacheWrite':0,'totalTokens':2,
    'cost':{'input':.01,'output':.01,'cacheRead':0,'cacheWrite':0,'total':.02}}}})
(Path(value('--session-dir'))/'fixture.jsonl').write_text(''.join(json.dumps(x)+'\\n' for x in e))
'''+("if preparing: Path('TASK.md').write_text('unexpected preparation edit')\n" if preparation_failure else '')
               +("if '--extension' in a and not preparing: print('Æ automatic handoff unavailable',file=sys.stderr)\n" if handoff_failure else ''))
            for path in (go, pi):
                path.chmod(0o700)
            args = argparse.Namespace(command='run', ae_root=root / 'ae', output=root / 'output',
                control_model='fixture/sol', ae_model='fixture/luna', control_thinking='high', ae_thinking='medium',
                pi=str(pi), test_timeout=5, agent_timeout=5, max_calls=35, max_tool_errors=4,
                preparation_timeout=5, preparation_max_calls=100,
                order='control,ae', race=True)

            node = tools / 'node'
            node.write_text('''#!/usr/bin/env python3
import json,sys,subprocess
from pathlib import Path
command=sys.argv[2]
if command == 'prepare-prompt':
    print('fixture preparation prompt')
elif command == 'read':
    revision=subprocess.check_output(['git','rev-parse','HEAD']).decode().strip()
    print(json.dumps({'writerLockPresent':False,'state':{
        'subjects':[{'id':'fixture'}], 'statements':[{'id':'note'}],
        'evidence':[{'kind':'file','revision':revision,'reference':'demo.go'}], 'relationships':[]}}))
else:
    raise SystemExit(2)
''')
            node.chmod(0o700)

            with mock.patch.object(bench, 'ROOT', harness), \
                    mock.patch.object(bench, 'ae_identity', return_value={'head': 'fixture'}), \
                    mock.patch.dict(os.environ, {'PATH': str(tools) + os.pathsep + os.environ['PATH']}), \
                    contextlib.redirect_stdout(io.StringIO()):
                success = bench.execute(args, 'caddy', source)
                self.assertEqual(success, not (handoff_failure or preparation_failure))
                run = next(args.output.iterdir())
                data = json.loads((run / 'results.json').read_text())
                if preparation_failure:
                    self.assertFalse(data['preparation']['valid'])
                    self.assertIn('preparation_changed_source', data['preparation']['problems'])
                    self.assertEqual(data['arms'], {})
                    self.assertFalse((run / 'logs/control-agent.json').exists())
                    self.assertFalse((run / 'logs/ae-agent.json').exists())
                    self.assertFalse((source / '.ae').exists())
                    self.assertEqual((source / 'demo.go').read_text(), 'baseline\n')
                    self.assertEqual((run / 'workspaces/preparation/TASK.md').read_text(), 'unexpected preparation edit')
                    return
                self.assertTrue(data['baseline']['baseline_red'])
                self.assertTrue(data['preparation']['valid'])
                self.assertEqual(data['preparation']['usage']['estimated_usd'], .02)
                self.assertIn('excluded from repair totals', data['preparation']['cost_scope'])
                self.assertEqual(data['arms']['ae']['usage']['estimated_usd'], .02)
                self.assertEqual((run / 'preparation-memory.ndjson').read_text(), 'fixture\n')
                self.assertTrue(data['arms']['control']['repair_verified'])
                self.assertTrue(data['arms']['ae']['repair_verified'])
                self.assertEqual((source / 'demo.go').read_text(), 'baseline\n')
                self.assertFalse((source / '.ae').exists())
                if handoff_failure:
                    self.assertIn('ae_extension_failure', data['arms']['ae']['problems'])
                    with self.assertRaises(ValueError):
                        bench.select(run, root / 'registry')
                else:
                    bench.select(run, root / 'registry')
                    entry = json.loads((root / 'registry/canonical.ndjson').read_text())
                    self.assertEqual(entry['case'], 'caddy')
                    self.assertEqual(entry['results_sha256'], bench.sha(run / 'results.json'))


if __name__ == '__main__':
    unittest.main()
