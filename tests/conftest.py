"""Test fixtures.

The default `client` runs the service in MOCK mode (SCGNN_MOCK=1), so the
endpoint/contract tests need neither the heavy stack nor the Hub. Revision
resolution is monkeypatched to a known SHA.

`real_client` (in test_worker.py) instead runs the real engine against a
controllable fake `scgnn.inference`, to exercise the worker pool.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

FAKE_SHA = "5f87610c80520e56935d789d95e4b370216d5423"


def _fresh_app(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from app import model_loader, settings as settings_module

    monkeypatch.setattr(model_loader, "resolve_revision", lambda repo_id, revision, token: FAKE_SHA)
    settings_module.get_settings.cache_clear()
    from app.main import create_app

    return create_app()


@pytest.fixture
def client(monkeypatch):
    app = _fresh_app(monkeypatch, SCGNN_MOCK="1")
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client_unresolvable(monkeypatch):
    """A mock client whose revision resolution fails (degraded path)."""
    from app import model_loader, settings as settings_module

    monkeypatch.setenv("SCGNN_MOCK", "1")

    def _boom(repo_id, revision, token):
        raise RuntimeError("hub unreachable")

    monkeypatch.setattr(model_loader, "resolve_revision", _boom)
    settings_module.get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c