import os
from pathlib import Path
import pytest
import mongomock
from stage8_support import ExternalOOMP, SECRETS, seed


@pytest.fixture(autouse=True)
def integration_environment(monkeypatch):
    for name in list(os.environ):
        if name.startswith("TRACE_OOMP_"):
            monkeypatch.delenv(name)
    for name,value in SECRETS.items():
        monkeypatch.setenv(name,value)


@pytest.fixture
def database():
    db=mongomock.MongoClient(tz_aware=True)["stage8-synthetic"]
    seed(db)
    return db


@pytest.fixture
def external_server(tmp_path):
    from stage8_support import EXTERNAL_PYTHON
    if not EXTERNAL_PYTHON.is_file():
        pytest.skip("External OOMP Python installation unavailable")
    server=ExternalOOMP(tmp_path)
    try:
        yield server
    finally:
        server.stop()