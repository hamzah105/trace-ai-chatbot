"""Network fault/resource checks around the SDK transport, not a custom MCP server."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import threading
import time
from types import SimpleNamespace

import pytest
from backend.services.oomp_client import OOMPClient,OOMPError
from stage8_support import configuration


@contextmanager
def fault_endpoint(*,delay=0,body=b"{}",status=200,location=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_POST(self):
            if self.headers.get("Content-Length"):
                self.rfile.read(int(self.headers["Content-Length"]))
            time.sleep(delay)
            try:
                self.send_response(status)
                self.send_header("Content-Type","application/json")
                self.send_header("Content-Length",str(len(body)))
                if location:
                    self.send_header("Location",location)
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):
                pass
    server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
    server.daemon_threads=True
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        yield SimpleNamespace(url=f"http://127.0.0.1:{server.server_port}/mcp")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def test_wall_timeout_bounds_stalled_network_request():
    with fault_endpoint(delay=.6) as endpoint:
        config=configuration(endpoint,mode="retrieve",timeout_seconds=.15)
        started=time.monotonic()
        with pytest.raises(OOMPError,match="timeout"):
            OOMPClient(config).retrieve("OOMP")
        assert time.monotonic()-started<2


def test_large_chunked_or_declared_response_fails_before_json_decode():
    with fault_endpoint(body=b"x"*1100000) as endpoint:
        with pytest.raises(OOMPError,match="response_limit"):
            OOMPClient(configuration(endpoint,mode="retrieve")).retrieve("OOMP")


def test_remote_redirect_cannot_receive_memory_credentials():
    with fault_endpoint(status=307,location="http://example.com/mcp") as endpoint:
        with pytest.raises(OOMPError,match="redirect_rejected"):
            OOMPClient(configuration(endpoint,mode="retrieve")).retrieve("OOMP")

def test_malformed_remote_validation_input_never_appears_in_sdk_logs(caplog):
    with fault_endpoint(body=b'"PRIVATE-RAW-MEMORY-CONTENT"') as endpoint:
        config=configuration(endpoint,mode="retrieve",timeout_seconds=.2)
        with pytest.raises(OOMPError):
            OOMPClient(config).retrieve("PRIVATE-USER-QUERY")
    assert "PRIVATE-RAW" not in caplog.text and "PRIVATE-USER-QUERY" not in caplog.text
    assert "Traceback" not in caplog.text