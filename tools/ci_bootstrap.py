"""Hosted/local CI offline bootstrap; invoke with stock/fresh Python -I -S -B.

No .pth, sitecustomize, prior venv startup hook, OOMP runtime, real model or real
Mongo service is loaded. Plain dependency paths are added without site.addsitedir.
Only the controller launches this file; all test subprocesses pass this guard.
"""
from __future__ import annotations
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import importlib.abc
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import sysconfig
import threading
import time

parser = argparse.ArgumentParser()
parser.add_argument('--spec', type=Path, required=True)
parser.add_argument('--script-b64')
args = parser.parse_args()
SPEC_PATH = args.spec.resolve()
SPEC = json.loads(SPEC_PATH.read_text(encoding='utf-8-sig'))
ROOT = Path(SPEC['repo']).resolve()
ARTIFACT = Path(SPEC['artifact']).resolve()
PHASE = Path(SPEC['phase']).resolve()
DEPS = Path(SPEC['dependencies']).resolve()
BASE = Path(sys.base_prefix).resolve()
STDLIB = Path(sysconfig.get_path('stdlib')).resolve()
BOOTSTRAP = Path(__file__).resolve()
MARKER = ARTIFACT/'offline-guard-violation.flag'
CANCEL_NAMES = ('CANCEL', 'CANCEL.flag', 'STOP', 'offline-guard-violation.flag')
if not sys.flags.isolated or not sys.flags.no_site:
    raise RuntimeError('isolated_no_site_startup_required')
if not PHASE.is_relative_to(ARTIFACT) or SPEC_PATH.parent != PHASE:
    raise RuntimeError('fresh_phase_paths_required')
if not DEPS.is_dir():
    raise RuntimeError('reviewed_plain_dependency_path_required')
if any((ARTIFACT/name).exists() for name in CANCEL_NAMES):
    raise RuntimeError('prior_cancellation_or_violation')
if Path(os.environ['HOME']).resolve() != PHASE/'home':
    raise RuntimeError('synthetic_home_required')
sys.dont_write_bytecode = True
# The reviewed pywin32.pth declares these three plain import directories.
# Add those paths explicitly without executing that .pth or its startup import.
_WINDOWS_DEP_PATHS = [DEPS/'win32', DEPS/'win32'/'lib', DEPS/'pythonwin'] if os.name=='nt' else []
if any(not path.is_dir() for path in _WINDOWS_DEP_PATHS):
    raise RuntimeError('reviewed_pywin32_plain_dependency_path_missing')
sys.path[:] = [str(ROOT), str(ROOT/'tests'), str(DEPS), *(str(path) for path in _WINDOWS_DEP_PATHS), *sys.path]
os.chdir(ROOT)
EVENTS = PHASE/'offline-events.jsonl'
_original_open = os.open
_original_write = os.write
_original_close = os.close
_log_lock = threading.RLock()
_active = threading.local()
_owned_ports = set()
_process_tickets = set()
_current_test = None


def emit(kind, **counts):
    # Fixed codes/counts only. Do not retain source, commands, tokens or URLs.
    if getattr(_active, 'logging', False):
        return
    _active.logging = True
    try:
        raw = (json.dumps({'kind':kind,'pid':os.getpid(),
            'monotonic':time.monotonic(),**counts}, sort_keys=True)+'\n').encode()
        with _log_lock:
            fd = _original_open(str(EVENTS), os.O_WRONLY|os.O_CREAT|os.O_APPEND, 0o600)
            try: _original_write(fd, raw)
            finally: _original_close(fd)
    finally:
        _active.logging = False


class ForbiddenOperation(BaseException):
    pass


def deny(code):
    emit('blocked', code=code)
    _active.logging = True
    try:
        fd = _original_open(str(MARKER), os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        try: _original_write(fd, code.encode('ascii'))
        finally: _original_close(fd)
    except FileExistsError:
        pass
    finally:
        _active.logging = False
    raise ForbiddenOperation(code)


# Exact native Windows null-device spellings only. Classify raw names before
# Path.resolve(), which can turn os.devnull into the device namespace. Ordinary
# filesystem paths such as ROOT/NUL receive the normal phase/private checks.
_NATIVE_NUL = object()


def canonical_path(raw):
    if isinstance(raw, int):
        return None
    try:
        decoded = os.fsdecode(raw)
        if decoded == os.devnull or os.name == 'nt' and decoded.lower() in {'nul', '\\\\.\\nul', '\\\\?\\nul'}:
            return _NATIVE_NUL
        # pytest/shutil uses extended local-drive spellings during rm_rf.
        # Remove only the exact \\?\<ASCII drive>:\ prefix before normal
        # resolution/containment checks; do not normalize UNC/device namespaces.
        if (os.name=='nt' and decoded.startswith(chr(92)*2+'?'+chr(92))
                and len(decoded)>=7 and decoded[4] in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
                and decoded[5]==':' and decoded[6]==chr(92)):
            decoded=decoded[4:]
        return Path(decoded).resolve()
    except (ValueError, TypeError, OSError):
        deny('unsupported_file_path')


def allowed_file(path, writing=False):
    if path is None or path is _NATIVE_NUL:
        return True
    if any(part.lower() in {'.aws','.ssh','.codex','.agents'} for part in path.parts):
        return False
    if path.name.lower() == '.env' or path.name.lower().startswith('.env.'):
        return False
    if writing:
        return path.is_relative_to(PHASE)
    if path.is_relative_to(ARTIFACT):
        return True
    if path.is_relative_to(DEPS) or path.is_relative_to(STDLIB) or path.is_relative_to(BASE/'DLLs') or (path.parent==BASE and path.name.lower() in {'python311.zip','python312.zip'}):
        return True
    if any(path.is_relative_to(ROOT/folder) for folder in ('backend','tests','frontend','docs','config','tools')):
        return True
    if path.parent == ROOT and path.name.lower() in {
        'pytest.ini','pyproject.toml','setup.cfg','tox.ini','requirements.txt',
        'requirements-dev.txt','requirements-oomp.txt','requirements-ci.txt','readme.md'}:
        return True
    if not writing and os.name != 'nt' and (
            any(path.is_relative_to(Path(name)) for name in ('/usr/share/zoneinfo','/usr/share/lib/zoneinfo','/etc/ssl/certs'))
            or path == Path('/etc/localtime').resolve()):
        return True
    return False


def loopback(host):
    if host == 'localhost':
        return True
    try:
        address = ipaddress.ip_address(host)
        return address.is_loopback or bool(getattr(address, 'ipv4_mapped', None) and address.ipv4_mapped.is_loopback)
    except (ValueError, TypeError):
        return False


def network_check(address, *, binding=False):
    if not isinstance(address, tuple) or len(address)<2:
        deny('unsupported_socket_address')
    host, port = address[:2]
    if port in {11434,27017,8765}:
        deny('model_database_or_existing_service_port')
    if not loopback(host):
        deny('external_network_or_dns')
    if binding:
        if port != 0:
            deny('only_owned_ephemeral_bind_allowed')
    elif port not in _owned_ports:
        deny('unowned_loopback_connection')


def blocked_file_diagnostic(path, *, writing):
    # No file contents, private absolute paths, source lines, locals, commands,
    # tokens or URLs. Only fixed path classes and reviewed public relative names.
    path_class = 'outside_allowed_roots'
    public_relative = None
    for label, public_root in (
        ('artifact', ARTIFACT), ('dependency', DEPS),
        ('stdlib', BASE/'Lib'), ('stdlib_dll', BASE/'DLLs'),
        *((name, ROOT/name) for name in ('backend','tests','frontend','docs','config','tools')),
    ):
        if path is not None and path is not _NATIVE_NUL and path.is_relative_to(public_root):
            path_class = label
            relative = path.relative_to(public_root).as_posix()
            if len(relative)<=240 and all(char.isalnum() or char in '._/-' for char in relative):
                public_relative = relative
            break
    if path is not None and path is not _NATIVE_NUL:
        if any(part.lower() in {'.aws','.ssh','.codex','.agents'} for part in path.parts):
            path_class = 'credential_or_private_directory'
            public_relative = None
        elif path.name.lower()=='.env' or path.name.lower().startswith('.env.'):
            path_class = 'dotenv_private_file'
            public_relative = None
    frames = []
    frame = sys._getframe(1)
    for unused in range(10):
        if frame is None:
            break
        module = frame.f_globals.get('__name__', '')
        function = frame.f_code.co_name
        if isinstance(module,str) and len(module)<=100 and all(char.isalnum() or char in '._' for char in module):
            if len(function)<=100 and all(char.isalnum() or char in '_<>' for char in function):
                frames.append({'module':module,'function':function})
        frame = frame.f_back
    emit('blocked_file_diagnostic', action='write' if writing else 'read',
        path_class=path_class, public_relative=public_relative,
        current_test=_current_test, frames=frames)

def audit(event, values):
    if getattr(_active, 'logging', False):
        return
    if event == 'open':
        path = canonical_path(values[0])
        flags = values[2] if len(values)>2 and isinstance(values[2], int) else 0
        mode = values[1] if len(values)>1 else ''
        writing = bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND)) or (isinstance(mode,str) and any(c in mode for c in 'wax+'))
        # CPython's compiler opens its exact synthetic filename to annotate a
        # SyntaxError/IndentationError. This raw name is invalid on Windows;
        # admit only the read so native error handling can proceed. Writes,
        # normalized filenames and every other synthetic name remain guarded.
        if os.name=='nt' and values[0]=='<unknown>' and not writing:
            return
        if not allowed_file(path, writing=writing):
            blocked_file_diagnostic(path, writing=writing)
            deny('private_read_or_outside_phase_write')
    elif event in {'os.remove','os.rmdir','os.mkdir','os.chmod','os.utime'}:
        path=canonical_path(values[0])
        if not allowed_file(path, writing=True):
            emit('blocked_mutation_diagnostic',mutation=event,current_test=_current_test)
            blocked_file_diagnostic(path,writing=True)
            deny('outside_phase_mutation')
    elif event in {'os.rename','os.replace','os.link','os.symlink'}:
        for value in values[:2]:
            path=canonical_path(value)
            if not allowed_file(path, writing=True):
                emit('blocked_mutation_diagnostic',mutation=event,current_test=_current_test)
                blocked_file_diagnostic(path,writing=True)
                deny('outside_phase_mutation')
    elif event in {'socket.connect','socket.connect_ex','socket.sendto'}:
        network_check(values[-1] if event=='socket.sendto' else values[1])
    elif event == 'socket.bind':
        network_check(values[1], binding=True)
    elif event in {'socket.getaddrinfo','socket.gethostbyname','socket.gethostbyaddr'}:
        if not loopback(values[0]):
            deny('external_network_or_dns')
    elif event == 'subprocess.Popen':
        command = values[1]
        ticket = command if isinstance(command,str) and os.name=='nt' else (tuple(command) if isinstance(command,(list,tuple)) else None)
        if ticket not in _process_tickets:
            deny('unreviewed_executable_or_service')
        _process_tickets.remove(ticket)
    elif event in {'os.system','os.exec','os.posix_spawn','os.spawn','pty.spawn'}:
        deny('unguarded_process_execution')


sys.addaudithook(audit)
_original_bind = socket.socket.bind

def guarded_bind(connection, address):
    network_check(address, binding=True)
    result = _original_bind(connection, address)
    actual = connection.getsockname()
    if not isinstance(actual, tuple) or not loopback(actual[0]) or actual[1] <= 0 or actual[1] in {11434,27017,8765}:
        deny('owned_ephemeral_port_invalid')
    _owned_ports.add(actual[1])
    emit('owned_ephemeral_bind', count=len(_owned_ports))
    return result

socket.socket.bind = guarded_bind


class NoLiveRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'oomp','torch','transformers','ollama','llama_cpp'}:
            deny('live_or_private_runtime_import')

sys.meta_path.insert(0, NoLiveRuntime())

# dotenv 1.1.1 has no disable switch. Patch the real reviewed package before any
# application import; retaining all other package functions avoids fake modules.
import dotenv

def no_dotenv(*unused, **ignored):
    emit('dotenv_suppressed')
    return False

def no_dotenv_find(*unused, **ignored):
    emit('dotenv_find_suppressed')
    return ''

dotenv.load_dotenv = no_dotenv
dotenv.find_dotenv = no_dotenv_find
import dotenv.main
dotenv.main.load_dotenv = no_dotenv
dotenv.main.find_dotenv = no_dotenv_find

_original_popen = subprocess.Popen
GIT = Path(SPEC['git']).resolve()
NODE = Path(SPEC['node']).resolve() if SPEC.get('node') else None
NODE_GUARD = ROOT/'tools'/'ci_node_guard.cjs'


class GuardedPopen(_original_popen):
    # Keep the public class interface required by asyncio.windows_utils.Popen.
    # All supported commands still pass the same transformation and audit ticket.
    def __init__(self, command, *positional, **kwargs):
        if kwargs.get('shell') or isinstance(command,(str,bytes)) or not isinstance(command,(tuple,list)):
            # Diagnose caller shape without recording arguments or commands.
            frames=[]
            frame=sys._getframe(1)
            for unused in range(10):
                if frame is None:
                    break
                module=frame.f_globals.get('__name__','')
                function=frame.f_code.co_name
                if isinstance(module,str) and len(module)<=100 and all(char.isalnum() or char in '._' for char in module):
                    if len(function)<=100 and all(char.isalnum() or char in '_<>' for char in function):
                        frames.append({'module':module,'function':function})
                frame=frame.f_back
            emit('blocked_process_shape_diagnostic', current_test=_current_test,
                shell_requested=bool(kwargs.get('shell')),
                command_is_string=isinstance(command,(str,bytes)),frames=frames)
            deny('unreviewed_process_shape')
        values = [os.fsdecode(value) for value in command]
        executable = Path(values[0]).resolve() if os.path.isabs(values[0]) else None
        python_command = executable == Path(sys.executable).resolve()
        if python_command and len(values)==3 and values[1]=='-c':
            encoded = base64.b64encode(values[2].encode()).decode('ascii')
            values = [sys.executable,'-I','-S','-B',str(BOOTSTRAP),'--spec',str(SPEC_PATH),'--script-b64',encoded]
            # Tests may set only synthetic runtime settings; inherited sanitized env
            # is kept, and child guard startup does not depend on PYTHONPATH/.pth.
            child_env = dict(kwargs.get('env') or os.environ)
            child_env['PYTHONDONTWRITEBYTECODE']='1'
            kwargs['env']=child_env
            emit('guarded_python_child')
        elif values in ([str(GIT),'show','6976c51:backend/routes/chat.py'],['git','show','6976c51:backend/routes/chat.py']):
            values[0]=str(GIT)
            child_env=dict(os.environ)
            child_env.update(GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull,
                GIT_TERMINAL_PROMPT='0',GIT_OPTIONAL_LOCKS='0',GIT_CONFIG_COUNT='1',
                GIT_CONFIG_KEY_0='safe.directory',GIT_CONFIG_VALUE_0=str(ROOT))
            kwargs['env']=child_env
            emit('read_only_git_child')
        elif NODE and (executable==NODE or values[0].lower() in {'node','node.exe'}) and _current_test and any(name in _current_test for name in ('test_phase3_dashboard_frontend.py','test_phase3_finalization_frontend.py')):
            if len(values)!=3 or values[1] not in {'-e','--check'}:
                deny('unreviewed_node_shape')
            if values[1]=='--check' and Path(values[2]).resolve()!=ROOT/'frontend'/'analytics.js':
                deny('unreviewed_node_input')
            values=[str(NODE),'--require',str(NODE_GUARD),*values[1:]]
            child_env=dict(os.environ)
            child_env.update(P4B_PHASE=str(PHASE),P4B_ARTIFACT=str(ARTIFACT),P4B_REPO=str(ROOT))
            kwargs['env']=child_env
            emit('guarded_node_child')
        else:
            deny('unreviewed_executable_or_service')
        if kwargs.get('executable'):
            deny('executable_override_forbidden')
        kwargs['creationflags']=kwargs.get('creationflags',0)|getattr(subprocess,'CREATE_NO_WINDOW',0)
        # Windows audits the exact list2cmdline string after native argument
        # normalization; POSIX audits the argument sequence. Both tickets are
        # created only here after the same reviewed command checks above.
        ticket=subprocess.list2cmdline(values) if os.name=='nt' else tuple(values)
        _process_tickets.add(ticket)
        try:
            _original_popen.__init__(self,values,*positional,**kwargs)
        finally:
            _process_tickets.discard(ticket)
subprocess.Popen = GuardedPopen
sys._trace_p4b_offline_guard={'enabled':True,'no_site':True,'dotenv_suppressed':True}
emit('guard_loaded', isolated=bool(sys.flags.isolated), no_site=bool(sys.flags.no_site),
    python=sys.version.split()[0], plain_dependency_path=True)


def check_cancel():
    if any((ARTIFACT/name).exists() for name in CANCEL_NAMES):
        raise ForbiddenOperation('cancellation_or_violation_latched')


# Diagnostic metadata only: pytest parses a statement fragment with the real
# relative filename 'source'. On Windows compiler error annotation opens that
# filename before reporting SyntaxError. Substitute an invalid synthetic filename
# only for this exact pytest caller, preserving AST semantics and file boundaries.
import ast
_original_ast_parse=ast.parse

def diagnostic_ast_parse(source, filename='<unknown>', mode='exec', **options):
    if filename=='source' and sys._getframe(1).f_globals.get('__name__')=='_pytest._code.source':
        filename='<unknown>'
    return _original_ast_parse(source,filename,mode,**options)

ast.parse=diagnostic_ast_parse

# JUnit's machine-name metadata must not trigger platform.uname() shell fallbacks
# or disclose the workstation hostname. This does not authorize any subprocess.
import platform
platform.node=lambda: 'p4b-offline-synthetic'

# Python 3.11 platform.win32_ver normally shells out to `ver` even though the
# native Windows version API is available. Supply that version metadata directly;
# shell execution remains denied and transport/TLS settings are untouched.
if os.name=='nt':
    def native_syscmd_ver(system='', release='', version='', supported_platforms=('win32','win16','dos')):
        if sys.platform not in supported_platforms:
            return system,release,version
        native=sys.getwindowsversion()
        components=native.platform_version or native[:3]
        return 'Windows',release,'.'.join(str(value) for value in components)
    platform._syscmd_ver=native_syscmd_ver

if args.script_b64:
    check_cancel()
    script=base64.b64decode(args.script_b64,validate=True).decode()
    sys.argv=['-c']
    exec(compile(script,'<guarded-synthetic-subprocess>','exec'),{'__name__':'__main__'})
else:
    import pytest
    class Accounting:
        def __init__(self):
            self.collected=0
            self.deselected=[]
            self.reports=[]
        def pytest_collection_modifyitems(self, config, items):
            policy = json.loads((ROOT/'tools'/'ci_policy.json').read_text(encoding='utf-8'))
            excluded = policy['excluded']
            frontend = set(policy['frontend_files'])
            retained, removed = [], []
            found = set()
            phase_removed = []
            for item in items:
                name = item.nodeid.split('::')[0]
                if item.nodeid in excluded:
                    found.add(item.nodeid)
                    removed.append(item)
                    self.deselected.append({'nodeid':item.nodeid,'reason':excluded[item.nodeid]})
                elif 'external_server' in item.fixturenames:
                    raise pytest.UsageError('Unclassified external-server test: '+item.nodeid)
                elif (SPEC['selection']=='python' and name in frontend) or (SPEC['selection']=='frontend' and name not in frontend):
                    removed.append(item)
                    phase_removed.append(item.nodeid)
                else:
                    retained.append(item)
            if found != set(excluded):
                raise pytest.UsageError('Service exclusion inventory changed')
            # Validate the declared optional SDK before measuring transport deadlines.
            # Keep every existing assertion; cold import time is recorded separately.
            readiness = 'tests/test_p4b_environment.py::test_enabled_adapter_dependencies_import_without_services'
            if SPEC['selection'] != 'frontend' and not any(item.nodeid == readiness for item in retained):
                raise pytest.UsageError('Dependency-readiness test missing')
            retained.sort(key=lambda item: item.nodeid != readiness)
            self.phase_removed = phase_removed
            if removed:
                items[:] = retained
                config.hook.pytest_deselected(items=removed)
        def pytest_collection_finish(self, session):
            self.collected=len(session.items)
        def pytest_runtest_setup(self,item):
            global _current_test
            check_cancel()
            _current_test=item.nodeid
        def pytest_runtest_logreport(self,report):
            self.reports.append({'nodeid':report.nodeid,'when':report.when,'outcome':report.outcome,
                'skip_reason':str(report.longrepr) if report.skipped else None,'duration_seconds':report.duration})
        def pytest_sessionfinish(self,session,exitstatus):
            payload={'exitstatus':int(exitstatus),'collected_after_deselection':self.collected,
                'boundary_deselected':self.deselected,'boundary_deselected_count':len(self.deselected),
                'phase_deselected':getattr(self,'phase_removed',[]),
                'reports':self.reports,'skipped_count':sum(row['outcome']=='skipped' for row in self.reports)}
            with (PHASE/'test-accounting.json').open('x',encoding='utf-8') as handle:
                json.dump(payload,handle,indent=2)
    accounting=Accounting()
    selected=SPEC.get('tests') or ['tests']
    if any(not value.startswith('tests') or '..' in value or Path(value.split('::')[0]).is_absolute() for value in selected):
        raise RuntimeError('public_test_selection_required')
    code=pytest.main(['-q','-ra','-p','no:cacheprovider','-o','junit_family=xunit1',*selected,
        '--basetemp='+str(PHASE/'tmp'), '--junitxml='+str(PHASE/'junit.xml')],plugins=[accounting])
    check_cancel()
    if any(row['outcome']=='skipped' for row in accounting.reports):
        raise RuntimeError('Unexpected selected-test skip; report platform limitation')
    raise SystemExit(int(code))
