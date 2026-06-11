"""
Integration test fixtures.

Runs the mock FastAPI backend in a background thread and provides
a sync ApiClient pointed at it.
"""

import threading
import time

import pytest
import uvicorn

from declaw.api.client import ApiClient
from declaw.connection_config import ConnectionConfig
from tests.mock_backend.app import app

_PORT = 19876
_BASE_URL = f"http://127.0.0.1:{_PORT}"


class _ServerThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.server = None

    def run(self):
        config = uvicorn.Config(app, host="127.0.0.1", port=_PORT, log_level="error")
        self.server = uvicorn.Server(config)
        self.server.run()

    def stop(self):
        if self.server:
            self.server.should_exit = True


_thread: _ServerThread | None = None


@pytest.fixture(scope="session", autouse=True)
def _start_mock_server():
    global _thread
    _thread = _ServerThread()
    _thread.start()
    # Wait for server to be ready
    import httpx

    for _ in range(30):
        try:
            httpx.get(f"{_BASE_URL}/sandboxes", timeout=1.0)
            break
        except Exception:
            time.sleep(0.1)
    yield
    if _thread:
        _thread.stop()


@pytest.fixture
def mock_client():
    config = ConnectionConfig(api_key="integration-test-key", api_url=_BASE_URL)
    return ApiClient(config, max_retries=1)


@pytest.fixture
def mock_config():
    return ConnectionConfig(api_key="integration-test-key", api_url=_BASE_URL)
