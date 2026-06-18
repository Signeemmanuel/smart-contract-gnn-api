"""Real-engine / worker-pool tests, run against the controllable fake
`scgnn.inference` (no torch/Slither). These exercise the process pool, the
wall-clock timeout + recycle, the structured error mapping and the bounded queue.

The fake is selected via env vars read inside the worker process (so they cross
the spawn boundary): FAKE_MODE = ok | error | hang, FAKE_LOAD = fail.
"""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

FAKE_SHA = "5f87610c80520e56935d789d95e4b370216d5423"


def _real_app(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("SCGNN_MOCK", "0")
    from app import model_loader, settings as settings_module

    monkeypatch.setattr(model_loader, "resolve_revision", lambda repo_id, revision, token: FAKE_SHA)
    settings_module.get_settings.cache_clear()
    from app.main import create_app

    return create_app()


def _poll(client, job_id, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/analyze/{job_id}").json()
        if body["status"] in {"done", "failed"}:
            return body
        time.sleep(0.1)
    raise AssertionError("job did not finish in time")


def test_real_health_reports_not_mock(monkeypatch):
    with TestClient(_real_app(monkeypatch, FAKE_MODE="ok")) as c:
        h = c.get("/health").json()
        assert h["mock_mode"] is False
        assert h["model_loaded"] is True
        assert h["resolved_sha"] == FAKE_SHA


def test_real_analysis_ok(monkeypatch):
    with TestClient(_real_app(monkeypatch, FAKE_MODE="ok")) as c:
        src = "contract C { function f() public { msg.sender.call.value(1)(\"\"); } }"
        jid = c.post("/analyze", json={"source": src}).json()["job_id"]
        body = _poll(c, jid)
        assert body["status"] == "done"
        assert body["result"]["flaws"][0]["type"] == "reentrancy"


def test_real_extraction_error_maps_to_failed(monkeypatch):
    with TestClient(_real_app(monkeypatch, FAKE_MODE="error")) as c:
        jid = c.post("/analyze", json={"source": "contract Broken {"}).json()["job_id"]
        body = _poll(c, jid)
        assert body["status"] == "failed"
        assert body["error"]["code"] == "extraction_failed"


def test_real_timeout_maps_to_failed(monkeypatch):
    # Tight timeout so the hanging fake trips it quickly, then the worker recycles.
    with TestClient(_real_app(monkeypatch, FAKE_MODE="hang", SCGNN_ANALYZE_TIMEOUT_S="2")) as c:
        jid = c.post("/analyze", json={"source": "contract Slow {}"}).json()["job_id"]
        body = _poll(c, jid, timeout=30.0)
        assert body["status"] == "failed"
        assert body["error"]["code"] == "timeout"


def test_queue_cap_returns_503(monkeypatch):
    # One worker, hanging analysis, queue cap of 1 -> the 2nd submission is shed.
    with TestClient(
        _real_app(monkeypatch, FAKE_MODE="hang", SCGNN_MAX_WORKERS="1",
                  SCGNN_QUEUE_MAX="1", SCGNN_ANALYZE_TIMEOUT_S="60")
    ) as c:
        first = c.post("/analyze", json={"source": "contract A {}"})
        assert first.status_code == 202
        time.sleep(0.3)  # let it become in-flight
        second = c.post("/analyze", json={"source": "contract B {}"})
        assert second.status_code == 503


def test_load_failure_keeps_service_up(monkeypatch):
    with TestClient(_real_app(monkeypatch, FAKE_LOAD="fail")) as c:
        h = c.get("/health").json()
        assert h["status"] == "ok"          # service stays up
        assert h["model_loaded"] is False
        assert h["error"] is not None