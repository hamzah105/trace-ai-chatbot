"""Synthetic CI guard probes; no app imports, private reads or live services."""
from __future__ import annotations
import ast
import importlib.abc
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import SimpleNamespace
import sys
import unittest

SOURCE = Path(__file__).with_name('ci_bootstrap.py').read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)
FUNCTIONS = {
    'allowed_file', 'canonical_path', 'loopback', 'network_check', 'audit',
    'no_dotenv', 'no_dotenv_find', 'NoLiveRuntime',
}
NODES = [node for node in TREE.body
         if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in FUNCTIONS
         or isinstance(node, ast.Assign)
         and any(isinstance(target, ast.Name) and target.id == 'POSIX_STDLIB_ZIP'
                 for target in node.targets)]
assert len(NODES) == len(FUNCTIONS) + 1, 'actual guard policy definitions required'
POLICY_CODE = compile(ast.Module(body=NODES, type_ignores=[]), '<actual-ci-policy>', 'exec')


class SyntheticPosixPath(PurePosixPath):
    def resolve(self):
        return self


class PolicyDenied(BaseException):
    pass


def policy(platform='posix', minor=11, platlibdir='lib', base=None):
    path_type = PureWindowsPath if platform == 'nt' else SyntheticPosixPath
    base = base or path_type('C:/synthetic/python' if platform == 'nt' else '/synthetic/python')
    root = path_type('C:/synthetic/repo' if platform == 'nt' else '/synthetic/repo')
    artifact = root/'data'/'fresh'
    def deny(code):
        raise PolicyDenied(code)
    fake_os = SimpleNamespace(name=platform, fsdecode=os.fsdecode,
                              devnull='nul' if platform == 'nt' else '/dev/null')
    for name in ('O_WRONLY', 'O_RDWR', 'O_CREAT', 'O_TRUNC', 'O_APPEND'):
        setattr(fake_os, name, getattr(os, name))
    namespace = dict(
        BASE=base, STDLIB=base/('Lib' if platform == 'nt' else f'lib/python3.{minor}'),
        ROOT=root, ARTIFACT=artifact, PHASE=artifact/'tests', DEPS=root/'dependencies',
        os=fake_os, sys=SimpleNamespace(platlibdir=platlibdir,
            version_info=SimpleNamespace(major=3, minor=minor), path=['/untrusted/arbitrary.zip']),
        Path=path_type, ipaddress=ipaddress, importlib=importlib,
        _NATIVE_NUL=object(), _active=SimpleNamespace(logging=False),
        _owned_ports={49152}, _process_tickets=set(), _current_test=None,
        deny=deny, emit=lambda *args, **kwargs: None,
        blocked_file_diagnostic=lambda *args, **kwargs: None,
    )
    exec(POLICY_CODE, namespace)
    return namespace


class GuardPolicyTests(unittest.TestCase):
    def setUp(self):
        self.p = policy()
        self.candidate = self.p['POSIX_STDLIB_ZIP']

    def test_candidate_uses_trusted_prefix_library_directory_and_runtime_version(self):
        for minor in (11, 12):
            for library in ('lib', 'lib64'):
                p = policy(minor=minor, platlibdir=library)
                self.assertEqual(p['POSIX_STDLIB_ZIP'],
                                 p['BASE']/library/f'python3{minor}.zip')

    def test_exact_candidate_read_is_admitted(self):
        self.assertTrue(self.p['allowed_file'](self.candidate))

    def test_absent_candidate_reaches_normal_file_not_found(self):
        # Simulate the native open after the real audit function; no file I/O.
        p = self.p
        p['Path'] = lambda raw: SimpleNamespace(resolve=lambda: self.candidate)
        p['audit']('open', (str(self.candidate), 'r', 0))
        def simulated_native_open():
            raise FileNotFoundError('synthetic absent interpreter archive')
        with self.assertRaises(FileNotFoundError):
            simulated_native_open()

    def test_sibling_archives_are_denied(self):
        for name in ('arbitrary.zip', 'python311.zip.bak', 'PYTHON311.ZIP'):
            self.assertFalse(self.p['allowed_file'](self.candidate.with_name(name)))

    def test_other_python_version_archives_are_denied(self):
        for name in ('python310.zip', 'python312.zip', 'python313.zip'):
            self.assertFalse(self.p['allowed_file'](self.candidate.with_name(name)))

    def test_parent_and_archive_descendants_are_denied(self):
        self.assertFalse(self.p['allowed_file'](self.candidate.parent))
        self.assertFalse(self.p['allowed_file'](self.candidate/'nested.zip'))

    def test_arbitrary_sys_path_zip_is_not_trusted(self):
        self.assertFalse(self.p['allowed_file'](PurePosixPath('/untrusted/arbitrary.zip')))

    def test_private_and_dotenv_reads_are_denied(self):
        for parent in (self.p['ROOT'], self.p['ARTIFACT'], self.p['BASE'], self.p['DEPS']):
            for name in ('.env', '.env.local', '.aws/config', '.ssh/id_rsa',
                         '.codex/auth.json', '.agents/private.json'):
                self.assertFalse(self.p['allowed_file'](parent/name))

    def test_private_denial_precedes_candidate_admission(self):
        p = policy(base=PurePosixPath('/synthetic/.aws/python'))
        self.assertFalse(p['allowed_file'](p['POSIX_STDLIB_ZIP']))

    def test_candidate_writes_are_denied_for_every_audited_open_mode(self):
        p = self.p
        p['Path'] = lambda raw: SimpleNamespace(resolve=lambda: self.candidate)
        self.assertFalse(p['allowed_file'](self.candidate, writing=True))
        for mode, flags in (('w', 0), ('a', 0), ('x', 0), ('r+', 0),
                            ('r', os.O_WRONLY), ('r', os.O_RDWR),
                            ('r', os.O_CREAT), ('r', os.O_TRUNC), ('r', os.O_APPEND)):
            with self.assertRaisesRegex(PolicyDenied, 'private_read_or_outside_phase_write'):
                p['audit']('open', (str(self.candidate), mode, flags))

    def test_candidate_mutations_and_directory_creation_are_denied(self):
        p = self.p
        p['Path'] = lambda raw: SimpleNamespace(resolve=lambda: self.candidate)
        for event in ('os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod', 'os.utime'):
            with self.assertRaisesRegex(PolicyDenied, 'outside_phase_mutation'):
                p['audit'](event, (str(self.candidate),))
        for event in ('os.rename', 'os.replace', 'os.link', 'os.symlink'):
            with self.assertRaisesRegex(PolicyDenied, 'outside_phase_mutation'):
                p['audit'](event, (str(self.candidate), str(self.candidate)))

    def test_canonicalized_symlink_escape_is_denied(self):
        # Synthetic resolver represents Path.resolve following an untrusted link.
        for target in ('/synthetic/private/secret.zip', '/synthetic/private/.aws/config'):
            p = policy()
            resolved_target = PurePosixPath(target)
            p['Path'] = lambda raw: SimpleNamespace(resolve=lambda: resolved_target)
            resolved = p['canonical_path'](str(p['POSIX_STDLIB_ZIP']))
            p['Path'] = SyntheticPosixPath
            self.assertEqual(resolved, resolved_target)
            self.assertNotEqual(resolved, p['POSIX_STDLIB_ZIP'])
            self.assertFalse(p['allowed_file'](resolved))

    def test_windows_interpreter_zip_rules_remain_unchanged(self):
        p = policy(platform='nt')
        self.assertIsNone(p['POSIX_STDLIB_ZIP'])
        for name in ('python311.zip', 'python312.zip', 'PYTHON311.ZIP'):
            self.assertTrue(p['allowed_file'](p['BASE']/name))
            self.assertFalse(p['allowed_file'](p['BASE']/name, writing=True))
        self.assertFalse(p['allowed_file'](p['BASE']/'python313.zip'))

    def test_model_mongo_and_external_oomp_ports_remain_denied(self):
        for port in (11434, 27017, 8765):
            with self.assertRaisesRegex(PolicyDenied, 'model_database_or_existing_service_port'):
                self.p['network_check'](('127.0.0.1', port))

    def test_external_hosts_and_dns_remain_denied(self):
        for host in ('203.0.113.1', 'example.invalid'):
            with self.assertRaisesRegex(PolicyDenied, 'external_network_or_dns'):
                self.p['network_check']((host, 443))
            with self.assertRaisesRegex(PolicyDenied, 'external_network_or_dns'):
                self.p['audit']('socket.getaddrinfo', (host, 443))

    def test_only_owned_ephemeral_loopback_is_admitted(self):
        self.p['network_check'](('127.0.0.1', 0), binding=True)
        self.p['network_check'](('127.0.0.1', 49152))
        with self.assertRaisesRegex(PolicyDenied, 'unowned_loopback_connection'):
            self.p['network_check'](('127.0.0.1', 49153))
        with self.assertRaisesRegex(PolicyDenied, 'only_owned_ephemeral_bind_allowed'):
            self.p['network_check'](('127.0.0.1', 49152), binding=True)

    def test_unreviewed_subprocess_and_shell_execution_remain_denied(self):
        for platform in ('posix', 'nt'):
            p = policy(platform=platform)
            with self.assertRaisesRegex(PolicyDenied, 'unreviewed_executable_or_service'):
                p['audit']('subprocess.Popen', ('synthetic', ['synthetic']))
            for event in ('os.system', 'os.exec', 'os.posix_spawn', 'os.spawn', 'pty.spawn'):
                with self.assertRaisesRegex(PolicyDenied, 'unguarded_process_execution'):
                    p['audit'](event, ('synthetic',))

    def test_dotenv_remains_suppressed(self):
        self.assertIs(self.p['no_dotenv']('synthetic-not-opened.env'), False)
        self.assertEqual(self.p['no_dotenv_find'](), '')

    def test_live_runtime_imports_remain_denied(self):
        finder = self.p['NoLiveRuntime']()
        for name in ('oomp', 'torch', 'transformers', 'ollama', 'llama_cpp'):
            with self.assertRaisesRegex(PolicyDenied, 'live_or_private_runtime_import'):
                finder.find_spec(name+'.synthetic')
        self.assertIsNone(finder.find_spec('synthetic_permitted_module'))

    def test_installed_interpreter_candidate_matches_isolated_startup(self):
        self.assertTrue(sys.flags.isolated and sys.flags.no_site)
        expected = (Path(sys.base_prefix).resolve()/sys.platlibdir/
                    f'python{sys.version_info.major}{sys.version_info.minor}.zip')
        if os.name == 'posix':
            # Compare only the independently derived exact candidate, never trust
            # arbitrary sys.path entries as an admission source.
            self.assertIn(str(expected), sys.path)
            self.assertEqual(expected.resolve(), expected)


if __name__ == '__main__':
    candidate = (Path(sys.base_prefix).resolve()/sys.platlibdir/
                 f'python{sys.version_info.major}{sys.version_info.minor}.zip')
    print(json.dumps(dict(
        kind='trusted_interpreter_zip_configuration',
        isolated=bool(sys.flags.isolated), no_site=bool(sys.flags.no_site),
        platform=os.name, base_prefix=str(Path(sys.base_prefix).resolve()),
        python=sys.version.split()[0], platlibdir=sys.platlibdir,
        posix_candidate=str(candidate) if os.name == 'posix' else None,
        candidate_in_isolated_startup_path=str(candidate) in sys.path if os.name == 'posix' else None,
        candidate_exists=candidate.exists() if os.name == 'posix' else None,
    )), flush=True)
    unittest.main(verbosity=2)
