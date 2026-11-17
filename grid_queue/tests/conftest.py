"""All test data is local; fail immediately on accidental network access."""
import shutil
import socket
import uuid
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('Network access is forbidden in tests')
    monkeypatch.setattr(socket, 'create_connection', blocked)
    monkeypatch.setattr(socket.socket, 'connect', blocked)


@pytest.fixture
def scratch_dir():
    # Create ordinary workspace directories; works in restricted Windows runners too.
    path = Path(__file__).parent / '.runs' / uuid.uuid4().hex
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path)
