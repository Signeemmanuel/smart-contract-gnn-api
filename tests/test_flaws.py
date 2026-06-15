from __future__ import annotations


def test_flaws_metadata(client):
    r = client.get("/flaws")
    assert r.status_code == 200
    body = r.json()
    codes = [f["type"] for f in body]
    # Canonical order and set, straight from scgnn.schema.
    assert codes == ["reentrancy", "access_control", "arithmetic", "unchecked_calls", "dos"]
    by_code = {f["type"]: f for f in body}
    assert by_code["arithmetic"]["name"] == "Integer Overflow/Underflow"
    assert by_code["arithmetic"]["dasp"] == 3
