from __future__ import annotations

from .conftest import FAKE_SHA


def test_health_reports_resolved_sha(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["model_loaded"] is True
    assert body["mock_mode"] is True
    assert body["resolved_sha"] == FAKE_SHA
    assert body["configured_revision"] == "production"
    assert body["device"] == "cpu"
    assert body["threshold"] == 0.5
    # The token value must never appear in the payload.
    assert "hf_token" not in body
    assert set(body) >= {"hf_token_present"}


def test_health_degrades_when_resolution_fails(client_unresolvable):
    r = client_unresolvable.get("/health")
    assert r.status_code == 200  # service stays up
    body = r.json()
    # The mock is still ready to serve (it needs no bundle), but it could not
    # resolve the real SHA, so that is null and the reason is surfaced.
    assert body["mock_mode"] is True
    assert body["resolved_sha"] is None
    assert body["error"] is not None