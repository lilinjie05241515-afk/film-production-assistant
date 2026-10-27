"""Rebuild and package the unified writer using isolated synthetic outputs."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import filmprod
from release import assemble, build_modules, publisher


class ScreenwriterReleaseTest(unittest.TestCase):
    def assert_runtime_versions(self, plugin, runtime, cwd, expected, isolated):
        """Run a fresh interpreter; an assembled MCP cannot reuse source imports."""
        env = {key: value for key, value in os.environ.items()
               if not key.upper().startswith(('PYTHON', 'FILMPROD_'))}
        env['FILMPROD_CATALOG_PATH'] = str(cwd / 'TEST-unused-catalog.sqlite3')
        requests = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
             'params': {'protocolVersion': '2025-11-25'}},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
             'params': {'name': 'film_health', 'arguments': {}}},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
             'params': {'name': 'film_modules', 'arguments': {}}},
            {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/list'},
        ]
        process = subprocess.run(
            [sys.executable, '-I', '-B', '-X', 'utf8', str(plugin / 'mcp_server.py')],
            cwd=cwd, env=env,
            input=''.join(json.dumps(request) + '\n' for request in requests),
            capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)
        replies = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual([reply['id'] for reply in replies], [1, 2, 3, 4], replies)
        for reply in replies:
            self.assertNotIn('error', reply, reply)
            self.assertFalse(reply['result'].get('isError'), reply)
        self.assertEqual(replies[0]['result']['serverInfo']['version'], expected)
        health = replies[1]['result']['structuredContent']
        self.assertEqual(health['version'], expected)
        self.assertEqual(Path(health['runtime_root']).resolve(), runtime.resolve())
        self.assertEqual(health['runtime_isolated'], isolated)
        modules = replies[2]['result']['structuredContent']
        self.assertEqual(modules['system_version'], expected)
        self.assertEqual(Path(modules['root']).resolve(),
                         (plugin / 'modules' if isolated else runtime / 'modules').resolve())
        self.assertTrue(modules['verified'])
        self.assertEqual(len(modules['modules']), 8)
        self.assertTrue({'screenwriter', 'film-art-director'} <= {m['id'] for m in modules['modules']})
        names = {tool['name'] for tool in replies[3]['result']['tools']}
        self.assertEqual(len(names), 26)
        self.assertTrue({'film_art', 'film_screenwriting'} <= names)
        self.assertFalse((cwd / 'TEST-unused-catalog.sqlite3').exists())

        # The packaged Python module itself must have the same identity, even if
        # a future adapter accidentally substitutes a constant for its version.
        probe = subprocess.run(
            [sys.executable, '-I', '-B', '-X', 'utf8', '-c',
             'import json,sys; sys.path.insert(0,sys.argv[1]); import filmprod; '
             'print(json.dumps({"version":filmprod.__version__,"file":filmprod.__file__}))',
             str(runtime)], cwd=cwd, env=env, capture_output=True,
            text=True, encoding='utf-8', timeout=30)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        identity = json.loads(probe.stdout)
        self.assertEqual(identity['version'], expected)
        self.assertEqual(Path(identity['file']).resolve(),
                         (runtime / 'filmprod/__init__.py').resolve())

    def assert_plugin_identity(self, plugin, expected):
        manifest = json.loads((plugin / '.codex-plugin/plugin.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['version'], expected)
        html = (plugin / 'ui/board.html').read_text(encoding='utf-8')
        self.assertIn(expected, html, 'UI must display current release version')
        app_info = re.search(
            r"appInfo\s*:\s*\{\s*name\s*:\s*['\"]film-production-agent-board['\"]"
            r"\s*,\s*version\s*:\s*(?:['\"]([^'\"]+)['\"]|(VERSION))", html)
        self.assertIsNotNone(app_info, 'UI initialize must declare the board app version')
        if app_info.group(2):
            version_constant = re.search(r"\bVERSION\s*=\s*['\"]([^'\"]+)['\"]", html)
            self.assertIsNotNone(version_constant, 'UI VERSION must have a literal value')
            self.assertEqual(version_constant.group(1), expected)
        else:
            self.assertEqual(app_info.group(1), expected)

    def test_source_runtime_manifest_health_and_initialize_versions_agree(self):
        source = Path(__file__).resolve().parents[1]
        self.assertEqual(Path(filmprod.__file__).resolve(),
                         (source / 'filmprod/__init__.py').resolve())
        expected = filmprod.__version__
        self.assert_plugin_identity(source / 'plugin', expected)
        with tempfile.TemporaryDirectory(prefix='film-writer-version-TEST-') as temporary:
            self.assert_runtime_versions(source / 'plugin', source, Path(temporary), expected, False)

    def test_self_contained_methods_rebuild_and_portable_payload(self):
        source = Path(__file__).resolve().parents[1]
        modules = source / 'modules'
        self.assertTrue(build_modules.verify(modules)['ok'])
        manifest = json.loads((modules / 'manifest.json').read_text(encoding='utf-8'))
        ids = {entry['id'] for entry in manifest['modules']}
        self.assertEqual(ids, {'screenwriter', 'director-agent', 'vfx-agent', 'seedance-prompt',
                               'film-analysis', 'idea-explorer', 'requirements-planner', 'film-art-director'})
        writer = next(entry for entry in manifest['modules'] if entry['id'] == 'screenwriter')
        art = next(entry for entry in manifest['modules'] if entry['id'] == 'film-art-director')
        with tempfile.TemporaryDirectory(prefix='film-writer-release-TEST-') as temporary:
            work = Path(temporary)
            config = work / 'sources.json'
            config.write_text(json.dumps({'base_modules': str(modules),
                'modules': {'screenwriter': str(modules / 'screenwriter')}}), encoding='utf-8')
            built = work / 'rebuilt'
            self.assertTrue(build_modules.build(config, built)['ok'])
            rebuilt_ids = {entry['id'] for entry in json.loads((built / 'manifest.json').read_text(encoding='utf-8'))['modules']}
            self.assertEqual(rebuilt_ids, ids)
            for entry in writer['files']:
                self.assertEqual((modules / entry['path']).read_bytes(), (built / entry['path']).read_bytes())
            for entry in art['files']:
                self.assertEqual((modules / entry['path']).read_bytes(), (built / entry['path']).read_bytes())
            payload = work / 'payload'
            assemble.assemble(source, payload)
            self.assertTrue((payload / 'plugin/skills/film-screenwriter/SKILL.md').is_file())
            self.assertTrue((payload / 'plugin/skills/film-art-director/SKILL.md').is_file())
            self.assertEqual({path.parent.name for path in (payload / 'plugin/skills').glob('*/SKILL.md')},
                             {'film-production-agent', 'film-screenwriter', 'film-director', 'film-art-director', 'film-brainstorm-interface'})
            self.assertFalse((payload / 'plugin/modules/novel-master').exists())
            self.assertFalse((payload / 'plugin/modules/novel-to-screenplay').exists())
            for generated in ('README.md', 'install.py', 'plugin/.mcp.json',
                              'plugin/.codex-plugin/plugin.json', 'plugin/docs/integration-skills.json'):
                self.assertNotIn(b'\r\n', (payload / generated).read_bytes(),
                                 'Generated payload bytes must be identical across build platforms')
            files = {p.relative_to(payload).as_posix(): p.read_bytes() for p in payload.rglob('*') if p.is_file()}
            self.assertEqual(publisher.inspect_payload(files), [])
            self.assertTrue(build_modules.verify(payload / 'plugin/modules')['ok'])
            self.assert_plugin_identity(payload / 'plugin', filmprod.__version__)
            self.assert_runtime_versions(payload / 'plugin', payload / 'plugin/runtime',
                                         payload, filmprod.__version__, True)


if __name__ == '__main__':
    unittest.main()
