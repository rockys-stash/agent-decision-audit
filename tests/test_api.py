"""API tests against a small demo deployment built in a temporary directory."""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentaudit.api.app import create_app
from agentaudit.api.demo import build_demo

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    var = tmp_path_factory.mktemp("var")
    mp = pytest.MonkeyPatch()
    mp.setenv("AGENTAUDIT_VAR", str(var))
    mp.delenv("AGENTAUDIT_DB", raising=False)
    mp.delenv("AGENTAUDIT_WITNESS", raising=False)
    mp.delenv("AGENTAUDIT_SIGNING_KEY", raising=False)
    mp.delenv("AGENTAUDIT_API_TOKEN", raising=False)
    build_demo(ROOT, seed=1, n_claims=150)
    yield var
    mp.undo()


@pytest.fixture(scope="module")
def client(env: Path) -> TestClient:
    return TestClient(create_app(ROOT, static_dir=env / "no-dist"))


def test_health_meta_and_security_headers(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.json() == {"status": "ok"}
    assert (
        r.headers["x-frame-options"] == "DENY"
        and "frame-ancestors 'none'" in r.headers["content-security-policy"]
    )
    m = client.get("/api/meta").json()
    assert (
        m["decisions"] == 150 and m["events"] > 3000 and m["checkpoints"] > 0 and m["anchors"] > 0
    )
    assert m["deployment"]["variant"] == "faulty" and m["levels"]["4"] == "L4 environment"


def test_case_list_filters_and_detail(client: TestClient) -> None:
    all_ = client.get("/api/cases?limit=500").json()
    assert all_["total"] == 150
    flagged = client.get("/api/cases?flagged=true&limit=500").json()["items"]
    assert flagged and all(c["findings"] > 0 for c in flagged)
    humans = client.get("/api/cases?decided_by=human&limit=500").json()["items"]
    assert humans and all(c["decided_by"] == "human" for c in humans)
    fx = client.get("/api/cases?decision_type=fx&limit=500").json()["items"]
    assert fx and all(c["simulation_truth"]["decision_type"] == "fx" for c in fx)
    detail = client.get(f"/api/cases/{all_['items'][0]['decision_id']}").json()
    ev = detail["events"]
    assert ev[0]["kind"] == "decision" and any(e["kind"] == "final" for e in ev)
    assert all(
        b["prev_hash"] == a["hash"] for a, b in itertools.pairwise(ev) if b["seq"] == a["seq"] + 1
    )
    assert all(c["status"] == "match" for c in detail["recomputation"])
    assert detail["simulation_truth"]["decision_type"]


def test_replay_levels_and_reference_code(client: TestClient) -> None:
    items = client.get("/api/cases?limit=500").json()["items"]
    did = items[0]["decision_id"]
    full = client.get(f"/api/cases/{did}/replay?level=4&mode=record").json()
    assert full["status"] in ("reproduced", "attested") and full["final_match"]
    assert {a["answer"] for a in full["answers"]} == {"record"}
    low = client.get(f"/api/cases/{did}/replay?level=0&mode=record&delay=180").json()
    assert low["status"] in ("unverifiable", "diverged", "not_reconstructable")
    violated = [
        c
        for c in items
        if c["simulation_truth"]["violation"] not in (None, "segregation_of_duties")
    ]
    assert violated
    deployed = client.get(
        f"/api/cases/{violated[0]['decision_id']}/replay?level=4&code=deployed"
    ).json()
    approved = client.get(
        f"/api/cases/{violated[0]['decision_id']}/replay?level=4&code=approved"
    ).json()
    assert deployed["status"] in ("reproduced", "attested")
    assert approved["status"] == "diverged" and approved["first_divergence"] is not None


def test_violations_and_standard(client: TestClient) -> None:
    v = client.get("/api/violations").json()
    assert v["items"] and sum(c["findings"] for c in v["checks"]) == len(v["items"])
    assert sum(v["injected"].values()) > 0
    s = client.get("/api/standard").json()
    assert s["id"] == "claims-audit-standard" and len(s["checks"]) >= 12


def test_integrity_and_tamper_lab_never_write(client: TestClient) -> None:
    before = client.get("/api/integrity").json()
    assert before["valid"] and before["checkpoints_checked"] > 0 and before["anchors_checked"] > 0
    lab = client.post("/api/integrity/tamper-lab", json={"attack": "edit_event", "seed": 3}).json()
    res = {r["defense"]: r for r in lab["results"]}
    assert res["sequence_only"]["valid"] and not res["hash_chain"]["valid"]
    assert res["hash_chain"]["first_bad_seq"] == lab["target_seq"]
    key = client.post(
        "/api/integrity/tamper-lab", json={"attack": "rewrite_with_key", "seed": 3}
    ).json()
    assert {r["defense"]: r["valid"] for r in key["results"]}[
        "chain_and_signed_checkpoints"
    ] is True
    assert (
        client.get("/api/integrity").json()["head"] == before["head"]
    )  # the real log is untouched
    assert (
        client.post("/api/integrity/tamper-lab", json={"attack": "drop_table"}).status_code == 422
    )


def test_input_validation_and_not_found(client: TestClient) -> None:
    assert client.get("/api/cases/claims-agent:NOPE").status_code == 404
    assert client.get("/api/cases/..%2F..%2Fetc").status_code in (400, 404)
    assert client.get("/api/cases/bad id/replay").status_code == 400
    assert client.get("/api/cases/claims-agent:CLM-00000/replay?level=9").status_code == 422
    assert client.get("/api/cases/claims-agent:CLM-00000/replay?mode=guess").status_code == 422
    assert client.get("/api/cases?search=<script>").status_code == 422
    assert client.get("/api/experiments/../../secret").status_code == 404
    assert client.get("/api/nothing-here").status_code == 404


def test_token_and_rate_limits(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTAUDIT_API_TOKEN", "test-read-token-123")
    c = TestClient(create_app(ROOT, static_dir=env / "no-dist"))
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/meta").status_code == 401
    assert (
        c.get("/api/meta", headers={"Authorization": "Bearer test-read-token-123"}).status_code
        == 200
    )
    h = {"Authorization": "Bearer test-read-token-123"}
    codes = [
        c.post("/api/integrity/tamper-lab", json={"attack": "delete_event"}, headers=h).status_code
        for _ in range(30)
    ]
    assert 429 in codes


def test_experiments_listing(client: TestClient) -> None:
    exps = client.get("/api/experiments").json()
    assert [e["experiment"] for e in exps][:2] == ["e1_reconstruction", "e2_audit_delay"]
    assert all(e["status"] in ("complete", "pending") for e in exps)


def test_integrity_detects_an_out_of_band_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An edit made directly in the database file shows up once the short verification cache expires."""
    import sqlite3

    import agentaudit.api.app as app_module

    monkeypatch.setenv("AGENTAUDIT_VAR", str(tmp_path))
    for k in (
        "AGENTAUDIT_DB",
        "AGENTAUDIT_WITNESS",
        "AGENTAUDIT_SIGNING_KEY",
        "AGENTAUDIT_API_TOKEN",
    ):
        monkeypatch.delenv(k, raising=False)
    db = build_demo(ROOT, seed=2, n_claims=40)
    monkeypatch.setattr(app_module, "VERIFY_TTL_S", 0.0)
    c = TestClient(create_app(ROOT, static_dir=tmp_path / "no-dist"))
    assert c.get("/api/integrity").json()["valid"]
    con = sqlite3.connect(db)
    con.execute("UPDATE events SET name = name || '-edited' WHERE seq = 200")
    con.commit()
    con.close()
    rep = c.get("/api/integrity").json()
    assert not rep["valid"] and rep["first_bad_seq"] == 200


def test_serve_refuses_a_public_host_without_a_token(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from agentaudit.cli import main

    monkeypatch.delenv("AGENTAUDIT_API_TOKEN", raising=False)
    assert main(["serve", "--host", "0.0.0.0"]) == 2
    assert "AGENTAUDIT_API_TOKEN" in capsys.readouterr().err
