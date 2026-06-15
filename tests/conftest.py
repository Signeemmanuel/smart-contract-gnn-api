"""Test fixtures.

The whole suite runs without the heavy extraction stack and without touching the
Hugging Face Hub: ``resolve_revision`` is monkeypatched, and analysis is the stub
engine. This mirrors the production intent that the test suite mocks the
expensive calls.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

FAKE_SHA = "5f87610c80520e56935d789d95e4b370216d5423"


@pytest.fixture
def client(monkeypatch):
    # Resolve to a known SHA without hitting the Hub.
    from app import model_loader

    monkeypatch.setattr(model_loader, "resolve_revision", lambda repo_id, revision, token: FAKE_SHA)

    # Rebuild settings (they are lru-cached) so any env set by a test is picked up.
    from app import settings as settings_module

    settings_module.get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client_unresolvable(monkeypatch):
    """A client whose revision resolution fails, to exercise the degraded path."""
    from app import model_loader

    def _boom(repo_id, revision, token):
        raise RuntimeError("hub unreachable")

    monkeypatch.setattr(model_loader, "resolve_revision", _boom)

    from app import settings as settings_module

    settings_module.get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c
