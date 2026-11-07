"""Opt-in local connection bootstrap. No OOMP imports or implicit service start."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import sys
from urllib.parse import urlsplit

LOCAL_FILE = ".oomp.local.json"


class LocalConnectionError(ValueError):
    def __init__(self):
        super().__init__("Invalid approved local OOMP connection")


def _require(condition):
    if not condition:
        raise LocalConnectionError()


def _safe(path):
    path = Path(path).absolute()
    _require(".." not in path.parts)
    for item in (*reversed(path.parents), path):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        _require(not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400)
        if item == path and stat.S_ISREG(info.st_mode):
            _require(info.st_nlink == 1)
    return path


def _windows_private(path):
    """Require protected explicit current-user/SYSTEM allow ACEs, no shell calls."""
    import ctypes as c
    from ctypes import wintypes as w
    adv, kernel = c.WinDLL("advapi32", use_last_error=True), c.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.LocalFree.argtypes = [c.c_void_p]
    adv.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)]
    adv.GetTokenInformation.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]
    adv.GetFileSecurityW.argtypes = [w.LPCWSTR, w.DWORD, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]
    adv.GetSecurityDescriptorControl.argtypes = [c.c_void_p, c.POINTER(w.WORD), c.POINTER(w.DWORD)]
    adv.GetSecurityDescriptorDacl.argtypes = [c.c_void_p, c.POINTER(w.BOOL), c.POINTER(c.c_void_p), c.POINTER(w.BOOL)]
    adv.ConvertStringSidToSidW.argtypes = [w.LPCWSTR, c.POINTER(c.c_void_p)]
    adv.GetAce.argtypes = [c.c_void_p, w.DWORD, c.POINTER(c.c_void_p)]
    adv.IsValidSid.argtypes = [c.c_void_p]
    adv.GetLengthSid.argtypes = [c.c_void_p]
    adv.GetLengthSid.restype = w.DWORD
    adv.EqualSid.argtypes = [c.c_void_p, c.c_void_p]
    token, system_sid = w.HANDLE(), c.c_void_p()
    try:
        _require(adv.OpenProcessToken(kernel.GetCurrentProcess(), 8, c.byref(token)))
        size = w.DWORD()
        adv.GetTokenInformation(token, 1, None, 0, c.byref(size))
        token_info = c.create_string_buffer(size.value)
        _require(adv.GetTokenInformation(token, 1, token_info, size, c.byref(size)))
        user_sid = c.cast(token_info, c.POINTER(c.c_void_p))[0]
        _require(adv.ConvertStringSidToSidW("S-1-5-18", c.byref(system_sid)))
        adv.GetFileSecurityW(str(path), 4, None, 0, c.byref(size))
        descriptor = c.create_string_buffer(size.value)
        _require(adv.GetFileSecurityW(str(path), 4, descriptor, size, c.byref(size)))
        control, revision = w.WORD(), w.DWORD()
        _require(adv.GetSecurityDescriptorControl(descriptor, c.byref(control), c.byref(revision)) and control.value & 0x1000)
        present, defaulted, acl = w.BOOL(), w.BOOL(), c.c_void_p()
        _require(adv.GetSecurityDescriptorDacl(descriptor, c.byref(present), c.byref(acl), c.byref(defaulted)) and present.value and acl.value)
        acl_size, count = c.c_ushort.from_address(acl.value+2).value, c.c_ushort.from_address(acl.value+4).value
        _require(count > 0)
        full_access = False
        for index in range(count):
            ace = c.c_void_p()
            _require(adv.GetAce(acl, index, c.byref(ace)) and ace.value)
            offset = ace.value-acl.value
            _require(8 <= offset <= acl_size-8)
            kind, flags, length = c.c_ubyte.from_address(ace.value).value, c.c_ubyte.from_address(ace.value+1).value, c.c_ushort.from_address(ace.value+2).value
            _require(kind == 0 and flags & ~3 == 0 and length >= 16 and offset+length <= acl_size)
            sid = ace.value+8
            _require(adv.IsValidSid(sid) and adv.GetLengthSid(sid) <= length-8)
            own = bool(adv.EqualSid(sid, user_sid))
            _require(own or adv.EqualSid(sid, system_sid))
            mask = c.c_uint32.from_address(ace.value+4).value
            full_access |= own and mask & 0x1F01FF == 0x1F01FF
        return full_access
    finally:
        if token:
            kernel.CloseHandle(token)
        if system_sid:
            kernel.LocalFree(system_sid)


def _private(path):
    path = _safe(path)
    if os.name == "nt":
        _require(_windows_private(path))
    else:
        info = path.stat()
        _require(info.st_uid == os.getuid() and not info.st_mode & 0o077)
    return path


def _object(pairs):
    value = {}
    for key, item in pairs:
        _require(key not in value)
        value[key] = item
    return value


def _read(path):
    path = _private(path)
    before = path.stat()
    with path.open("rb") as stream:
        info, raw = os.fstat(stream.fileno()), stream.read(65537)
    _require((before.st_dev, before.st_ino) == (info.st_dev, info.st_ino) and len(raw) <= 65536)
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_object,
                      parse_constant=lambda value: _require(False))


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def load_local_connection(project=None, *, environment=None):
    """Apply one private signed connection before routes read memory policy.

    Missing local file preserves baseline behavior. Invalid or conflicting files
    fail closed; no other profile/owner is selected and no credential is printed.
    """
    root = _safe(project or Path(__file__).resolve().parents[2])
    target = _safe(root/LOCAL_FILE)
    if not target.exists():
        return {"configured": False}
    env = os.environ if environment is None else environment
    try:
        config = _read(target)
        _require(set(config) == {"format", "project", "profile_home", "profile_name", "generation", "owner_id", "scope", "retrieval_api", "source_sha256", "signature"})
        _require(config["format"] == "oomp.trace.local.v1" and _safe(config["project"]) == root)
        name, generation = config["profile_name"], config["generation"]
        _require(re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", name) and re.fullmatch(r"[a-f0-9]{64}", generation))
        home = _private(config["profile_home"])
        directory = _private(home/name)
        _require(_read(directory/"active.json") == {"generation": generation})
        gen = _private(directory/"generations"/generation)
        _require(set(config["source_sha256"]) == {"profile.json", "server.json", "writers.json"})
        sources = {}
        for filename, expected in config["source_sha256"].items():
            path = _private(gen/filename)
            sources[filename] = _read(path)
            _require(hashlib.sha256(path.read_bytes()).hexdigest() == expected)
        profile, server, writers = sources["profile.json"], sources["server.json"], sources["writers.json"]
        identity_data = profile.copy()
        for field in ("extraction", "context_enabled"):
            if identity_data.get(field) is None:
                identity_data.pop(field, None)
        _require(hashlib.sha256(json.dumps(identity_data, sort_keys=True).encode()).hexdigest() == generation)
        _require(profile["name"] == name and profile["adapter"] == "trace" and profile["secret_source"] == "file")
        _require(_safe(profile["project"]) == root and profile["owner_id"] == config["owner_id"])
        _require(config["scope"] == {"tenant": profile["tenant"], "namespace": profile["namespace"], "principal": profile["principal"]})
        secrets = _read(directory/"secrets.json")
        prefix = "OOMP_"+name.upper().replace("-", "_")+"_"
        owner_key, read_token = secrets[prefix+"OWNER_KEY"], secrets[prefix+"READ_TOKEN"]
        _require(all(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{43,256}", value) for value in secrets.values()))
        _require(len(set(secrets.values())) == len(secrets))
        body = {key: value for key, value in config.items() if key != "signature"}
        _require(hmac.compare_digest(hmac.new(owner_key.encode("ascii"), _canonical(body), hashlib.sha256).hexdigest(), config["signature"]))
        # Signed explicit connection settings precede legacy dotenv defaults.
        # Keep a declared dotenv owner bound to the same approved identity.
        # database.py loads other dotenv defaults later with override=False.
        from dotenv import dotenv_values
        dotenv_owner = dotenv_values(root/".env").get("TRACE_OOMP_OWNER_ID")
        _require(not dotenv_owner or dotenv_owner == profile["owner_id"])
        _require(config["retrieval_api"] == ("context_v1" if profile.get("context_enabled") else "retrieve"))
        _require(server.get("context_enabled", False) == bool(profile.get("context_enabled")))
        host = server.get("host", "127.0.0.1")
        _require(ipaddress.ip_address(host).is_loopback and server["port"] == profile["port"])
        mode = "retrieve_and_ingest" if profile["mode"] == "trusted-ingest" else "retrieve"
        mongo_uri, mongo_database = _mongo_settings(root)
        _require(profile.get("mongo_database") in (None, mongo_database))
        values = {"MONGO_URI": mongo_uri, "MONGO_DB_NAME": mongo_database,
            "TRACE_OOMP_MODE": mode, "TRACE_OOMP_RETRIEVAL_API": config["retrieval_api"],
            "TRACE_OOMP_URL": "http://"+("["+host+"]" if ":" in host else host)+":"+str(server["port"])+"/mcp",
            "TRACE_OOMP_TRACE_ORIGIN": profile["host_origin"], "TRACE_OOMP_OWNER_ID": profile["owner_id"],
            "TRACE_OOMP_TENANT_ID": profile["tenant"], "TRACE_OOMP_NAMESPACE": profile["namespace"],
            "TRACE_OOMP_PRINCIPAL_ID": profile["principal"], "TRACE_OOMP_SOURCE_SYSTEM": "trace-ai",
            "TRACE_OOMP_READ_TOKEN": read_token, "TRACE_OOMP_OWNER_KEY": owner_key,
            "TRACE_OOMP_RETRIEVAL_MODE": "lexical"}
        if mode == "retrieve_and_ingest":
            _require(set(writers) == {"user", "assistant", "feedback"})
            values["TRACE_OOMP_WRITER_CONFIG"] = str(gen/"writers.json")
            for grant in writers.values():
                _require((grant["tenant_id"], grant["namespace"], grant["principal_id"]) ==
                         (profile["tenant"], profile["namespace"], profile["principal"]))
                for field in ("bearer_token_env", "approval_key_env"):
                    reference = grant[field]
                    _require(reference.startswith(prefix) and reference in secrets)
                    values[reference] = secrets[reference]
        else:
            _require(writers == {})
        # Check every value before mutation: partial activation is forbidden.
        _require(all(key not in env or env[key] == value for key, value in values.items()))
        env.update(values)
        return {"configured": True, "retrieval_api": config["retrieval_api"], "mode": mode}
    except Exception:
        raise LocalConnectionError() from None


def _mongo_settings(project):
    from dotenv import dotenv_values
    values = dotenv_values(_safe(project)/".env")
    uri = values.get("MONGO_URI") or "mongodb://localhost:27017/"
    database = values.get("MONGO_DB_NAME") or "trace_ai"
    parsed = urlsplit(uri)
    _require(parsed.scheme == "mongodb" and "," not in parsed.netloc)
    _require(parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname or "").is_loopback)
    _require(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", database))
    return uri, database


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only approved local TRACE discovery")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--inspect", action="store_true")
    group.add_argument("--connection", action="store_true", help="Private parent pipe only; never print this mode interactively")
    parser.add_argument("--owner-id")
    args = parser.parse_args(argv)
    try:
        project = Path(__file__).resolve().parents[2]
        uri, database = _mongo_settings(project)
        validated = False
        if args.owner_id is not None:
            _require(re.fullmatch(r"[0-9a-fA-F]{24}", args.owner_id))
            from bson import ObjectId
            from pymongo import MongoClient
            with MongoClient(uri, connect=False, directConnection=True, serverSelectionTimeoutMS=2000,
                             connectTimeoutMS=2000, socketTimeoutMS=2000, timeoutMS=3000) as client:
                validated = client[database]["users"].find_one({"_id": ObjectId(args.owner_id)}, {"_id": 1}) is not None
        result = {"ok": True, "python": sys.executable, "mongo_database": database,
                  "mongo_uri_env": "OOMP_TRACE_MONGO_URI", "mongo_configured": True,
                  "owner_validated": validated}
        if args.connection:
            # Used only by OOMP's captured private pipe. No file/log persistence.
            _require(not sys.stdout.isatty())
            result["mongo_uri"] = uri
        print(json.dumps(result))
        return 0
    except Exception:
        print(json.dumps({"ok": False, "code": "local_trace_inspection_failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
