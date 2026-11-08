"""Independent synthetic local-bootstrap checks; no OOMP imports or database IO."""
import hashlib
import hmac
from io import StringIO
import json
import os
from pathlib import Path
import sys
import types

import pytest
import dotenv
from dotenv import dotenv_values as parse_dotenv_values
from dotenv.main import DotEnv

from backend.services import oomp_local as local


def protect(path, *, broad=False):
    if os.name != 'nt':
        path.chmod(0o777 if broad else 0o700 if path.is_dir() else 0o600)
        return
    import ctypes as c
    from ctypes import wintypes as w
    api, kernel = c.WinDLL('advapi32'), c.WinDLL('kernel32')
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.LocalFree.argtypes = [c.c_void_p]
    api.OpenProcessToken.argtypes = [w.HANDLE,w.DWORD,c.POINTER(w.HANDLE)]
    api.GetTokenInformation.argtypes = [w.HANDLE,c.c_int,c.c_void_p,w.DWORD,c.POINTER(w.DWORD)]
    api.ConvertSidToStringSidW.argtypes = [c.c_void_p,c.POINTER(w.LPWSTR)]
    api.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR,w.DWORD,c.POINTER(c.c_void_p),c.POINTER(w.DWORD)]
    api.SetFileSecurityW.argtypes = [w.LPCWSTR,w.DWORD,c.c_void_p]
    token, sid_text, descriptor = w.HANDLE(), w.LPWSTR(), c.c_void_p()
    try:
        assert api.OpenProcessToken(kernel.GetCurrentProcess(),8,c.byref(token))
        size=w.DWORD(); api.GetTokenInformation(token,1,None,0,c.byref(size))
        buffer=c.create_string_buffer(size.value)
        assert api.GetTokenInformation(token,1,buffer,size,c.byref(size))
        assert api.ConvertSidToStringSidW(c.cast(buffer,c.POINTER(c.c_void_p))[0],c.byref(sid_text))
        flags='OICI' if path.is_dir() else ''
        sddl=f'D:P(A;{flags};FA;;;{sid_text.value})(A;{flags};FA;;;SY)'+(f'(A;{flags};FA;;;WD)' if broad else '')
        assert api.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl,1,c.byref(descriptor),None)
        assert api.SetFileSecurityW(str(path),0x80000004,descriptor)
    finally:
        if token: kernel.CloseHandle(token)
        if sid_text: kernel.LocalFree(c.cast(sid_text,c.c_void_p))
        if descriptor: kernel.LocalFree(descriptor)


def write(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')
    protect(path)


class InMemoryDotenv:
    """Real stream parsing behind hooks for one exact fictional dotenv path."""
    def __init__(self, path, text):
        self.path = path
        self.text = text

    def require_path(self, path):
        if Path(path) != self.path:
            raise ValueError('unregistered synthetic dotenv path')

    def values(self, path):
        self.require_path(path)
        return parse_dotenv_values(stream=StringIO(self.text))

    def load(self, path, *, override=False):
        self.require_path(path)
        # CI suppresses the global loader. Exercise its real stream semantics
        # only inside this fixture; do not restore a filesystem-capable loader.
        return DotEnv(dotenv_path=None, stream=StringIO(self.text),
                      override=override).set_as_environment_variables()


@pytest.fixture
def synthetic_dotenv(tmp_path, monkeypatch):
    source = InMemoryDotenv(tmp_path/'trace'/'.env',
        'MONGO_URI=mongodb://127.0.0.1:27017/\nMONGO_DB_NAME=fictional\n')
    monkeypatch.setattr(dotenv, 'dotenv_values', source.values)
    monkeypatch.setattr(dotenv, 'load_dotenv', source.load)
    return source


@pytest.fixture
def connection(tmp_path, synthetic_dotenv):
    root=tmp_path/'trace'; root.mkdir()
    home=tmp_path/'p'; home.mkdir(); protect(home)
    directory=home/'reader'; directory.mkdir(); protect(directory)
    profile={'name':'reader','adapter':'trace','project':str(root),'secret_source':'file',
        'owner_id':'000000000000000000000001','tenant':'fictional','namespace':'isolated',
        'principal':'owner','mode':'read-only','port':18765,'host_origin':'http://127.0.0.1:8000',
        'context_enabled':True,'mongo_database':'fictional'}
    generation=hashlib.sha256(json.dumps(profile,sort_keys=True).encode()).hexdigest()
    generations=directory/'generations'; generations.mkdir(); protect(generations)
    gen=generations/generation; gen.mkdir(); protect(gen)
    write(directory/'active.json', {'generation':generation})
    key='A'*43
    write(directory/'secrets.json', {'OOMP_READER_OWNER_KEY':key,'OOMP_READER_READ_TOKEN':'B'*43})
    write(gen/'profile.json',profile)
    write(gen/'server.json',{'host':'127.0.0.1','port':18765,'context_enabled':True})
    write(gen/'writers.json',{})
    body={'format':'oomp.trace.local.v1','project':str(root),'profile_home':str(home),
        'profile_name':'reader','generation':generation,'owner_id':profile['owner_id'],
        'scope':{'tenant':'fictional','namespace':'isolated','principal':'owner'},
        'retrieval_api':'context_v1',
        'source_sha256':{name:hashlib.sha256((gen/name).read_bytes()).hexdigest()
                         for name in ('profile.json','server.json','writers.json')}}
    body['signature']=hmac.new(key.encode(),local._canonical(body),hashlib.sha256).hexdigest()
    write(root/local.LOCAL_FILE,body)
    return root,directory,gen,body


def test_missing_file_keeps_memory_off_without_env_mutation(tmp_path):
    env={'UNRELATED':'keep'}
    assert local.load_local_connection(tmp_path,environment=env)=={'configured':False}
    assert env=={'UNRELATED':'keep'}


def test_independent_reference_handoff_reuses_secrets_in_memory_only(connection):
    root,directory,gen,body=connection
    before={path:path.read_bytes() for path in directory.rglob('*.json')}
    env={}
    result=local.load_local_connection(root,environment=env)
    assert result=={'configured':True,'retrieval_api':'context_v1','mode':'retrieve'}
    assert env['TRACE_OOMP_OWNER_ID']==body['owner_id']
    assert env['TRACE_OOMP_READ_TOKEN']=='B'*43 and env['TRACE_OOMP_OWNER_KEY']=='A'*43
    assert env['MONGO_DB_NAME']=='fictional'
    assert 'A'*43 not in (root/local.LOCAL_FILE).read_text()
    assert before=={path:path.read_bytes() for path in before}


@pytest.mark.parametrize('field,value',[
    ('TRACE_OOMP_OWNER_ID','foreign-owner'),('TRACE_OOMP_MODE','off'),
    ('MONGO_DB_NAME','other_database'),('MONGO_URI','mongodb://127.0.0.1:27018/'),
])
def test_conflicting_process_settings_fail_before_memory_activation(connection,field,value):
    root,*_=connection
    env={field:value,'UNRELATED':'keep'}
    with pytest.raises(local.LocalConnectionError):
        local.load_local_connection(root,environment=env)
    assert env=={field:value,'UNRELATED':'keep'}


@pytest.mark.parametrize('change',['owner','scope','signature','source'])
def test_tampering_rejected_with_static_safe_error(connection,change):
    root,directory,gen,body=connection
    if change=='owner': body['owner_id']='different-owner'
    elif change=='scope': body['scope']['namespace']='foreign'
    elif change=='signature': body['signature']='0'*64
    else: write(gen/'server.json',{'host':'127.0.0.1','port':18766,'context_enabled':True})
    write(root/local.LOCAL_FILE,body)
    env={}
    with pytest.raises(local.LocalConnectionError) as error:
        local.load_local_connection(root,environment=env)
    assert str(error.value)=='Invalid approved local OOMP connection' and env=={}
    assert 'A'*43 not in str(error.value) and 'B'*43 not in str(error.value)


def test_broad_local_file_permissions_rejected(connection):
    root,*_=connection
    protect(root/local.LOCAL_FILE,broad=True)
    with pytest.raises(local.LocalConnectionError):
        local.load_local_connection(root,environment={})


def test_hardlinked_secret_file_rejected(connection):
    root,directory,*_=connection
    os.link(directory/'secrets.json',directory/'secret-link.json')
    with pytest.raises(local.LocalConnectionError):
        local.load_local_connection(root,environment={})


def test_duplicate_json_keys_rejected(connection):
    root,*_=connection
    path=root/local.LOCAL_FILE
    path.write_text('{"format":"oomp.trace.local.v1","format":"another"}')
    with pytest.raises(local.LocalConnectionError):
        local.load_local_connection(root,environment={})


def test_inspection_queries_exact_selected_user_projection_only(monkeypatch,capsys):
    calls=[]
    class Collection:
        def find_one(self, query, projection):
            calls.append((query,projection)); return {'_id':query['_id']}
    class Client:
        def __init__(self,*args,**kwargs): pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def __getitem__(self,name):return self if name=='fictional' else Collection()
    monkeypatch.setattr(local,'_mongo_settings',lambda project:('mongodb://127.0.0.1:27017/','fictional'))
    monkeypatch.setitem(sys.modules,'pymongo',types.SimpleNamespace(MongoClient=Client))
    monkeypatch.setitem(sys.modules,'bson',types.SimpleNamespace(ObjectId=lambda value:value))
    owner='000000000000000000000001'
    assert local.main(['--inspect','--owner-id',owner])==0
    assert calls==[({'_id':owner},{'_id':1})]
    result=json.loads(capsys.readouterr().out)
    assert result['owner_validated'] and 'mongo_uri' not in result


def clear_process_memory_settings(monkeypatch):
    # Bootstrap mutates its process environment directly. Isolate those writes
    # as well as existing values so no synthetic credential outlives this test.
    isolated={name:value for name,value in os.environ.items()
        if not name.startswith(('TRACE_OOMP_', 'OOMP_READER_'))
        and name not in {'MONGO_URI','MONGO_DB_NAME'}}
    monkeypatch.setattr(os,'environ',isolated)


def trusted_connection(connection):
    """Create a distinct, fully signed fictional publication fixture."""
    root,directory,old_gen,body=connection
    profile=json.loads((old_gen/'profile.json').read_text())
    profile['mode']='trusted-ingest'
    generation=hashlib.sha256(json.dumps(profile,sort_keys=True).encode()).hexdigest()
    gen=directory/'generations'/generation
    gen.mkdir(); protect(gen)
    write(directory/'active.json',{'generation':generation})
    write(gen/'profile.json',profile)
    write(gen/'server.json',json.loads((old_gen/'server.json').read_text()))
    secrets={'OOMP_READER_OWNER_KEY':'A'*43,'OOMP_READER_READ_TOKEN':'B'*43}
    writers={}
    for index,role in enumerate(('user','assistant','feedback')):
        bearer='OOMP_READER_'+role.upper()+'_TOKEN'
        approval='OOMP_READER_'+role.upper()+'_APPROVAL'
        secrets[bearer]=chr(ord('C')+index*2)*43
        secrets[approval]=chr(ord('D')+index*2)*43
        writers[role]={'grant_id':'host-'+role,'principal_id':'owner','tenant_id':'fictional',
            'namespace':'isolated','source_type':'assistant' if role=='assistant' else 'user',
            'source_system':'trace-ai','event_types':['feedback' if role=='feedback' else role+'_message'],
            'bearer_token_env':bearer,'approval_key_env':approval}
    write(directory/'secrets.json',secrets)
    write(gen/'writers.json',writers)
    body={key:value for key,value in body.items() if key!='signature'}
    body['generation']=generation
    body['source_sha256']={name:hashlib.sha256((gen/name).read_bytes()).hexdigest()
        for name in ('profile.json','server.json','writers.json')}
    body['signature']=hmac.new(secrets['OOMP_READER_OWNER_KEY'].encode(),local._canonical(body),hashlib.sha256).hexdigest()
    write(root/local.LOCAL_FILE,body)
    return root,directory,gen,body


@pytest.mark.parametrize('publication',[False,True])
def test_signed_handoff_precedes_same_owner_legacy_dotenv_without_file_edits(connection,synthetic_dotenv,monkeypatch,publication):
    if publication:
        connection=trusted_connection(connection)
    root,directory,gen,body=connection
    clear_process_memory_settings(monkeypatch)
    legacy=(f'TRACE_OOMP_OWNER_ID={body["owner_id"]}\n'
        'MONGO_URI=mongodb://127.0.0.1:27017/\nMONGO_DB_NAME=fictional\n'
        'TRACE_OOMP_MODE=retrieve_and_ingest\nTRACE_OOMP_URL=http://127.0.0.1:19999/mcp\n'
        'TRACE_OOMP_TENANT_ID=legacy-tenant\nTRACE_OOMP_PRINCIPAL_ID=legacy-principal\n'
        'TRACE_OOMP_READ_TOKEN='+('Y'*43)+'\nTRACE_OOMP_OWNER_KEY='+('Z'*43)+'\n'
        'TRACE_OOMP_WRITER_CONFIG=legacy-writers.json\nUNRELATED_TRACE_DEFAULT=retained\n')
    synthetic_dotenv.text=legacy
    before_dotenv=synthetic_dotenv.text
    before={path:path.read_bytes() for path in (root/local.LOCAL_FILE,
        directory/'secrets.json',directory/'active.json')}
    result=local.load_local_connection(root)
    assert result['mode']==('retrieve_and_ingest' if publication else 'retrieve')
    assert os.environ['TRACE_OOMP_OWNER_ID']==body['owner_id']
    assert os.environ['TRACE_OOMP_URL']=='http://127.0.0.1:18765/mcp'
    assert os.environ['TRACE_OOMP_TENANT_ID']=='fictional'
    assert os.environ['TRACE_OOMP_PRINCIPAL_ID']=='owner'
    assert os.environ['TRACE_OOMP_READ_TOKEN']=='B'*43
    assert os.environ['TRACE_OOMP_OWNER_KEY']=='A'*43
    if publication:
        assert os.environ['TRACE_OOMP_WRITER_CONFIG']==str(gen/'writers.json')
        for grant in json.loads((gen/'writers.json').read_text()).values():
            assert os.environ[grant['bearer_token_env']]!=os.environ[grant['approval_key_env']]
    # Simulate database.py's normal later dotenv defaults; approved values persist.
    from dotenv import load_dotenv
    load_dotenv(root/'.env',override=False)
    assert os.environ['TRACE_OOMP_URL']=='http://127.0.0.1:18765/mcp'
    assert os.environ['TRACE_OOMP_OWNER_KEY']=='A'*43
    assert os.environ['UNRELATED_TRACE_DEFAULT']=='retained'
    assert synthetic_dotenv.text==before_dotenv and not synthetic_dotenv.path.exists()
    assert before=={path:path.read_bytes() for path in before}


def test_foreign_dotenv_owner_fails_without_partial_memory_activation(connection,synthetic_dotenv):
    root,*_=connection
    synthetic_dotenv.text='MONGO_DB_NAME=fictional\nTRACE_OOMP_OWNER_ID=000000000000000000000002\n'
    before=synthetic_dotenv.text
    env={'UNRELATED':'keep'}
    with pytest.raises(local.LocalConnectionError):
        local.load_local_connection(root,environment=env)
    assert env=={'UNRELATED':'keep'}
    assert synthetic_dotenv.text==before and not synthetic_dotenv.path.exists()


@pytest.mark.parametrize('field,value',[
    ('TRACE_OOMP_OWNER_ID','foreign-owner'),
    ('TRACE_OOMP_URL','http://127.0.0.1:19999/mcp'),
    ('TRACE_OOMP_TENANT_ID','foreign-tenant'),
    ('TRACE_OOMP_READ_TOKEN','Z'*43),
])
def test_explicit_process_settings_still_reject_with_same_owner_dotenv(connection,synthetic_dotenv,monkeypatch,field,value):
    root,_,_,body=connection
    clear_process_memory_settings(monkeypatch)
    synthetic_dotenv.text=f'TRACE_OOMP_OWNER_ID={body["owner_id"]}\nMONGO_DB_NAME=fictional\n'
    monkeypatch.setenv(field,value)
    before=dict(os.environ)
    with pytest.raises(local.LocalConnectionError):
        local.load_local_connection(root)
    assert dict(os.environ)==before


def test_in_memory_dotenv_preserves_real_parser_and_override_semantics(synthetic_dotenv,monkeypatch):
    monkeypatch.setattr(os,'environ',{'TRACE_TEST_LITERAL':'existing'})
    synthetic_dotenv.text="TRACE_TEST_LITERAL='fictional # quoted'\nTRACE_TEST_NUMBER=42\n"
    before=synthetic_dotenv.text
    assert dotenv.dotenv_values(synthetic_dotenv.path)=={
        'TRACE_TEST_LITERAL':'fictional # quoted','TRACE_TEST_NUMBER':'42'}
    assert dotenv.load_dotenv(synthetic_dotenv.path,override=False)
    assert os.environ=={'TRACE_TEST_LITERAL':'existing','TRACE_TEST_NUMBER':'42'}
    assert dotenv.load_dotenv(synthetic_dotenv.path,override=True)
    assert os.environ['TRACE_TEST_LITERAL']=='fictional # quoted'
    assert synthetic_dotenv.text==before and not synthetic_dotenv.path.exists()


@pytest.mark.parametrize('operation',['values','load'])
def test_in_memory_dotenv_rejects_unregistered_paths(synthetic_dotenv,operation):
    foreign=synthetic_dotenv.path.parent.parent/'foreign'/'.env'
    with pytest.raises(ValueError,match='unregistered synthetic dotenv path'):
        getattr(synthetic_dotenv,operation)(foreign)
    assert not synthetic_dotenv.path.exists() and not foreign.exists()
