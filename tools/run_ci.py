"""Run the declared synthetic suite in a fresh guarded child; no app services."""
from __future__ import annotations
import argparse
import ast
import ctypes
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import sysconfig
import time

ROOT = Path(__file__).resolve().parents[1]


def write_json(path, value):
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, indent=2)


def fixture_integrity():
    folder = ROOT/'tests/fixtures/p4b/v1'
    policy = json.loads((ROOT/'tools/ci_policy.json').read_text())
    for name, expected in policy['metadata_normalized_sha256'].items():
        assert hashlib.sha256((folder/name).read_bytes().replace(b'\r\n', b'\n')).hexdigest() == expected, name
    manifest = json.loads((folder/'manifest.json').read_bytes())
    results = []
    for entry in manifest['files']:
        raw = (folder/entry['file']).read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        assert actual == entry['sha256'] and len(raw) == entry['bytes'], entry['file']
        if entry['file'] == 'preregistration.md':
            assert b'\r' not in raw, 'preregistration must remain LF-only'
        results.append(dict(file=entry['file'], bytes=len(raw), sha256=actual))
    return results


def source_snapshot():
    # Hash only Git-visible public paths; never inspect ignored private files.
    git = shutil.which('git')
    if not git:
        raise RuntimeError('readonly_git_required')
    raw = subprocess.run([git,'ls-files','--cached','--others','--exclude-standard','-z'],
                         cwd=ROOT,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout
    files = []
    for name in raw.decode('utf-8').strip('\0').split('\0'):
        path = ROOT/name
        if ((name.split('/')[0] in {'backend','tests','tools','frontend','docs','.github'}
             and path.suffix in {'.py','.cjs','.js','.html','.css','.json','.md','.yml','.yaml'})
                or name in {'pytest.ini','.gitattributes'} or name.startswith('requirements') and name.endswith('.txt')):
            files.append(path)
    snapshot = {}
    for path in sorted(set(files)):
        assert path.resolve().is_relative_to(ROOT), 'public source symlink escaped repository'
        snapshot[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def classify():
    policy = json.loads((ROOT/'tools/ci_policy.json').read_text())
    rows = []
    for path in sorted((ROOT/'tests').glob('test_*.py')):
        name = path.relative_to(ROOT).as_posix()
        def visit(nodes, prefix=''):
            for node in nodes:
                if isinstance(node, ast.ClassDef):
                    visit(node.body, prefix+node.name+'::')
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('test_'):
                    identifier = name+'::'+prefix+node.name
                    category = policy['excluded'].get(identifier)
                    category = 'excluded: '+category if category else ('synthetic Node' if name in policy['frontend_files'] else 'synthetic/mocked Python')
                    rows.append(dict(nodeid=identifier, category=category))
        visit(ast.parse(path.read_bytes()).body)
    assert set(policy['excluded']) <= {row['nodeid'] for row in rows}
    return rows


class WindowsJob:
    """Kill only this controller's owned process tree on close/deadline."""
    def __init__(self):
        from ctypes import wintypes as w
        class Basic(ctypes.Structure):
            _fields_ = [('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),('flags',w.DWORD),
                        ('min_ws',ctypes.c_size_t),('max_ws',ctypes.c_size_t),('active',w.DWORD),
                        ('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name,ctypes.c_ulonglong) for name in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
        class Extended(ctypes.Structure):
            _fields_ = [('basic',Basic),('io',IO),('process_limit',ctypes.c_size_t),('job_limit',ctypes.c_size_t),
                        ('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        self.api.CreateJobObjectW.restype = w.HANDLE
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p,w.LPCWSTR]
        self.api.SetInformationJobObject.argtypes = [w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]
        self.api.AssignProcessToJobObject.argtypes = [w.HANDLE,w.HANDLE]
        self.api.CloseHandle.argtypes = [w.HANDLE]
        self.handle = self.api.CreateJobObjectW(None,None)
        if not self.handle:
            raise RuntimeError('owned_job_create_failed')
        limits = Extended(); limits.basic.flags = 0x2000
        if not self.api.SetInformationJobObject(self.handle,9,ctypes.byref(limits),ctypes.sizeof(limits)):
            self.close(); raise RuntimeError('owned_job_limits_failed')
    def assign(self, process):
        if not self.api.AssignProcessToJobObject(self.handle,int(process._handle)):
            process.kill(); raise RuntimeError('owned_job_assignment_failed')
    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle); self.handle = None


def resources():
    if os.name == 'nt':
        from ctypes import wintypes as w
        class Perf(ctypes.Structure):
            _fields_ = [('size',w.DWORD)] + [(name,ctypes.c_size_t) for name in
                ('commit_total','commit_limit','commit_peak','physical_total','available','cache','kernel_total','kernel_paged','kernel_nonpaged','page_size')] + [(name,w.DWORD) for name in ('handles','processes','threads')]
        value = Perf(); value.size = ctypes.sizeof(Perf)
        if not ctypes.WinDLL('psapi').GetPerformanceInfo(ctypes.byref(value),value.size):
            raise RuntimeError('resource_monitor_failed')
        return dict(available_ram_bytes=value.available*value.page_size,
                    commit_ratio=value.commit_total/value.commit_limit)
    available = os.sysconf('SC_AVPHYS_PAGES')*os.sysconf('SC_PAGE_SIZE')
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith('MemAvailable:'):
            available = int(line.split()[1])*1024
            break
    return dict(available_ram_bytes=available,commit_ratio=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts',type=Path,required=True)
    parser.add_argument('--selection',choices=('python','frontend','all'),default='all')
    parser.add_argument('--dependencies',type=Path,help='Reviewed read-only dependency path for isolated local validation only')
    parser.add_argument('--node',type=Path)
    parser.add_argument('--deadline-seconds',type=int,default=900)
    args = parser.parse_args()
    if not sys.flags.isolated or not sys.flags.no_site or not 30 <= args.deadline_seconds <= 1200:
        raise RuntimeError('isolated_bounded_startup_required')
    artifact = args.artifacts.resolve()
    if artifact.exists():
        raise RuntimeError('fresh_artifact_directory_required')
    artifact.mkdir(parents=True)
    phase = artifact/'tests'; phase.mkdir()
    record = dict(selection=args.selection,python=sys.version.split()[0],platform=sys.platform,passed=False)
    process = job = None
    started = time.monotonic()
    try:
        preflight = resources(); record['preflight'] = preflight
        if preflight['available_ram_bytes'] < 4*1024**3 or (preflight['commit_ratio'] is not None and preflight['commit_ratio']>=.75):
            raise RuntimeError('resource_admission_failed')
        deps = (args.dependencies or Path(sysconfig.get_path('purelib'))).resolve()
        if not deps.is_dir(): raise RuntimeError('declared_dependencies_missing')
        node = (args.node or Path(shutil.which('node') or 'missing-node')).resolve()
        git = Path(shutil.which('git') or 'missing-git').resolve()
        if not node.is_file() or not git.is_file(): raise RuntimeError('declared_node_and_git_required')
        write_json(artifact/'fixture-integrity.json',fixture_integrity())
        write_json(artifact/'test-classification.json',classify())
        write_json(artifact/'dependency-versions.json',sorted(
            [dict(name=d.metadata['Name'],version=d.version) for d in importlib.metadata.distributions(path=[str(deps)])],key=lambda row:row['name'].lower()))
        before = source_snapshot(); write_json(artifact/'source-before.json',before)
        for name in ('home','local','roaming','temp'):(phase/name).mkdir()
        env = {name:os.environ[name] for name in ('SystemRoot','WINDIR','COMSPEC','NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE','OS','LANG') if name in os.environ}
        env.update(PATH=os.pathsep.join([str(git.parent),str(node.parent),os.path.join(os.environ.get('SystemRoot','/usr'),'System32')]),
            HOME=str(phase/'home'),USERPROFILE=str(phase/'home'),LOCALAPPDATA=str(phase/'local'),APPDATA=str(phase/'roaming'),
            TEMP=str(phase/'temp'),TMP=str(phase/'temp'),TMPDIR=str(phase/'temp'),PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',PYTHONDONTWRITEBYTECODE='1',
            TRACE_TEST_OOMP_PYTHON=str(phase/'never-installed-oomp-python'),TRACE_OOMP_MODE='off',
            MONGO_URI='mongodb://127.0.0.1:27017/ci-forbidden',MONGO_DB_NAME='ci-forbidden',NO_PROXY='*')
        spec = dict(repo=str(ROOT),artifact=str(artifact),phase=str(phase),dependencies=str(deps),
                    git=str(git),node=str(node),tests=['tests'],selection=args.selection)
        write_json(phase/'spec.json',spec)
        command = [sys.executable,'-I','-S','-B','-X','utf8',str(ROOT/'tools/ci_bootstrap.py'),'--spec',str(phase/'spec.json')]
        write_json(artifact/'command.json',dict(command=command,ambient_environment_cleared=True,service_exclusions=9))
        with (phase/'stdout.txt').open('xb') as stdout,(phase/'stderr.txt').open('xb') as stderr,(artifact/'resource-samples.jsonl').open('x') as samples:
            if os.name=='nt':job = WindowsJob()
            process = subprocess.Popen(command,cwd=ROOT,env=env,stdout=stdout,stderr=stderr,
                start_new_session=os.name!='nt',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if job:job.assign(process)
            record['owned_pid'] = process.pid
            last = time.monotonic()
            while True:
                now = time.monotonic(); sample = resources()
                sample['elapsed_seconds'] = now-started
                samples.write(json.dumps(sample)+'\n'); samples.flush()
                if now-last > 3:raise RuntimeError('resource_monitor_stale')
                last = now
                if sample['available_ram_bytes']<1.5*1024**3 or (sample['commit_ratio'] is not None and sample['commit_ratio']>=.85):
                    raise RuntimeError('resource_pressure_stop')
                if any((artifact/name).exists() for name in ('CANCEL','CANCEL.flag','STOP','offline-guard-violation.flag')):
                    raise RuntimeError('cancellation_or_offline_guard_stop')
                if now-started > args.deadline_seconds:raise RuntimeError('deadline')
                if any((phase/name).stat().st_size>8*1024**2 for name in ('stdout.txt','stderr.txt')):raise RuntimeError('output_limit')
                if process.poll() is not None:break
                time.sleep(.5)
            record['exit_code'] = process.returncode
        if process.returncode:raise RuntimeError('selected_tests_failed')
        after = source_snapshot(); write_json(artifact/'source-after.json',after)
        if before!=after:raise RuntimeError('public_source_changed_during_tests')
        fixture_integrity()
        record['passed'] = True
    except BaseException as error:
        record['failure'] = str(error) if isinstance(error,RuntimeError) else type(error).__name__
    finally:
        if job:job.close()
        elif process:
            try:os.killpg(process.pid,signal.SIGTERM)
            except ProcessLookupError:pass
        if process and process.poll() is None:
            process.wait(timeout=10)
        record['elapsed_seconds'] = time.monotonic()-started
        write_json(artifact/'run-record.json',record)
        for name in ('stdout.txt','stderr.txt'):
            path = phase/name
            if path.exists():print(path.read_text(encoding='utf-8',errors='replace'),end='')
        print(json.dumps(record,indent=2))
    return 0 if record['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())