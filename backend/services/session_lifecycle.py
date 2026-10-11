"""Process-local serialization for session writes and finalization.

Entries include waiting callers in their reference count, so idle session locks
are removed without allowing two locks for the same session at once.
"""

from contextlib import contextmanager
from threading import Lock, RLock


_registry_guard = Lock()
_entries = {}


@contextmanager
def session_lifecycle(session_id):
    with _registry_guard:
        entry = _entries.get(session_id)
        if entry is None:
            entry = [RLock(), 0]
            _entries[session_id] = entry
        entry[1] += 1
    try:
        with entry[0]:
            yield
    finally:
        with _registry_guard:
            entry[1] -= 1
            if entry[1] == 0:
                del _entries[session_id]
