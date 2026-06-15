from __future__ import annotations

import time


def _poll(client, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/analyze/{job_id}")
        assert r.status_code == 200
        body = r.json()
        if body["status"] in {"done", "failed"}:
            return body
        time.sleep(0.05)
    raise AssertionError("job did not finish in time")


def test_analyze_json_lifecycle_and_shape(client):
    src = "contract C { function f() public { msg.sender.call.value(1)(\"\"); } }"
    r = client.post("/analyze", json={"source": src})
    assert r.status_code == 202
    submit = r.json()
    assert submit["status"] == "queued"
    job_id = submit["job_id"]

    body = _poll(client, job_id)
    assert body["status"] == "done"
    result = body["result"]
    # Exact wire contract from scgnn.schema.
    assert set(result) == {"source", "flaws", "degraded"}
    assert result["source"] == src
    assert result["degraded"] is False
    assert len(result["flaws"]) == 1
    flaw = result["flaws"][0]
    assert set(flaw) == {"type", "confidence", "lines"}
    assert flaw["type"] == "reentrancy"
    assert flaw["lines"] == [42, 47, 53]  # order preserved, not re-sorted


def test_analyze_clean_contract_returns_empty_flaws(client):
    r = client.post("/analyze", json={"source": "contract Safe { uint x; }"})
    job_id = r.json()["job_id"]
    body = _poll(client, job_id)
    assert body["status"] == "done"
    assert body["result"]["flaws"] == []


def test_empty_source_rejected(client):
    r = client.post("/analyze", json={"source": "   "})
    assert r.status_code == 422


def test_missing_source_rejected(client):
    r = client.post("/analyze", json={})
    assert r.status_code == 422


def test_file_upload_accepted(client):
    files = {"file": ("Token.sol", b"contract T { uint x; }", "text/plain")}
    r = client.post("/analyze/file", files=files)
    assert r.status_code == 202
    body = _poll(client, r.json()["job_id"])
    assert body["status"] == "done"
    assert body["result"]["source"] == "contract T { uint x; }"


def test_file_wrong_extension_rejected(client):
    files = {"file": ("notes.txt", b"contract T {}", "text/plain")}
    r = client.post("/analyze/file", files=files)
    assert r.status_code == 422


def test_file_non_utf8_rejected(client):
    files = {"file": ("bad.sol", b"\xff\xfe\x00bad", "application/octet-stream")}
    r = client.post("/analyze/file", files=files)
    assert r.status_code == 422


def test_file_too_large_rejected(client, monkeypatch):
    # Default cap is 256 KiB; send more.
    big = b"a" * (256 * 1024 + 10)
    files = {"file": ("big.sol", big, "text/plain")}
    r = client.post("/analyze/file", files=files)
    assert r.status_code == 413


def test_unknown_job_id_404(client):
    r = client.get("/analyze/does-not-exist")
    assert r.status_code == 404
