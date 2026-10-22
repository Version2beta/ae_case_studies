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
    def test_all_shipped_seeds_pass_screening(self):
        for spec in json.loads((bench.ROOT / 'cases.json').read_text()).values():
            bench.screen_seed(spec)

    def test_restic_screening_rejects_identifier_and_paraphrased_hazard(self):
        spec = json.loads((bench.ROOT / 'cases.json').read_text())['restic']
        for clue in ['HasAtomicReplace', 'atomic replacement', 'pre-deleting config', 'upgrade_repo.go']:
            with self.subTest(clue=clue):
                contaminated = {**spec, 'seed': [{'text': clue}]}
                with self.assertRaises(ValueError):
                    bench.screen_seed(contaminated)

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

    def test_check_runs_seed_query_and_preserves_artifact_invariants(self):
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
if command == 'init':
    (project / '.ae').mkdir()
    (project / '.ae/journal.ndjson').write_text('')
elif command == 'apply':
    with (project / '.ae/journal.ndjson').open('a') as journal:
        journal.write(sys.stdin.read())
elif command == 'query':
    print('fixture query')
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
            self.assertIn('seed_sha256', result)
            self.assertNotIn('error', result)
            self.assertTrue((run / 'logs/seed-query.json').is_file())
            self.assertTrue((run / 'report.md').is_file())
            self.assertIn('logs/seed-query.json', result['evidence_sha256'])

    def run_pair(self, handoff_failure):
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
Path('demo.go').write_text('fixed\\n')
e=[{'type':'session','id':'fixture'},
   {'type':'model_change','provider':value('--provider'),'modelId':value('--model')},
   {'type':'thinking_level_change','thinkingLevel':value('--thinking')}]
if '--extension' in a:
    e.append({'type':'custom_message','customType':'ae-context','content':'Layout context'})
e.append({'type':'message','message':{'role':'assistant','provider':value('--provider'),'model':value('--model'),
    'usage':{'input':1,'output':1,'cacheRead':0,'cacheWrite':0,'totalTokens':2,
    'cost':{'input':.01,'output':.01,'cacheRead':0,'cacheWrite':0,'total':.02}}}})
(Path(value('--session-dir'))/'fixture.jsonl').write_text(''.join(json.dumps(x)+'\\n' for x in e))
'''+("if '--extension' in a: print('Æ automatic handoff unavailable',file=sys.stderr)\n" if handoff_failure else ''))
            for path in (go, pi):
                path.chmod(0o700)
            args = argparse.Namespace(command='run', ae_root=root / 'ae', output=root / 'output',
                control_model='fixture/sol', ae_model='fixture/luna', control_thinking='high', ae_thinking='medium',
                pi=str(pi), test_timeout=5, agent_timeout=5, max_calls=35, max_tool_errors=4,
                order='control,ae', race=True)

            def seed(workspace, spec, ae_root, logs):
                store = workspace / '.ae'
                store.mkdir()
                journal = store / 'journal.ndjson'
                journal.write_text('fixture\n')
                return bench.sha(journal)

            with mock.patch.object(bench, 'ROOT', harness), mock.patch.object(bench, 'seed_memory', seed), \
                    mock.patch.object(bench, 'ae_identity', return_value={'head': 'fixture'}), \
                    mock.patch.dict(os.environ, {'PATH': str(tools) + os.pathsep + os.environ['PATH']}), \
                    contextlib.redirect_stdout(io.StringIO()):
                success = bench.execute(args, 'caddy', source)
                self.assertEqual(success, not handoff_failure)
                run = next(args.output.iterdir())
                data = json.loads((run / 'results.json').read_text())
                self.assertTrue(data['baseline']['baseline_red'])
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
