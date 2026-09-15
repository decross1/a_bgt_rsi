from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.applied_data_collection import project_market_research, register


def test_missing_root_is_not_started_without_side_effects(tmp_path):
    root = tmp_path / "missing"
    result = project_market_research(root)
    assert result["status"] == "not_started"
    assert result["batches"] == []
    assert result["paper_result"] == "not_tested"
    assert not root.exists()


def test_redirected_root_is_unavailable(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    root = tmp_path / "redirect"
    root.symlink_to(target, target_is_directory=True)
    result = project_market_research(root)
    assert result["status"] == "unavailable"
    assert not result["scan_complete"]


def test_projection_uses_source_verifier_and_removes_private_fields(tmp_path, monkeypatch):
    from bench.applied_trading import collection_projection
    name = "spot-BTCUSDT-20260915T140000Z"
    (tmp_path / name).mkdir()
    received = []
    def project(directory):
        received.append(directory)
        return {"collector_source_verified": True, "collector_source_status": "current_verified", "symbol": "BTCUSDT", "status": "incomplete",
                "source_valid_frames": 2, "requests_attempted": 3, "requests_succeeded": 2,
                "requests_failed": 1, "raw_private_response": "MUST NOT BE EXPORTED"}
    monkeypatch.setattr(collection_projection, "project_known_collection", project)
    result = project_market_research(tmp_path)
    assert received == [tmp_path / name]
    assert result["status"] == "data_recorded"
    assert result["batches"][0]["requests_failed"] == 1
    assert "raw_private_response" not in result["batches"][0]
    assert result["paper_result"] == "not_tested"
    assert all(stage["status"] == "not_recorded" for stage in result["stages"][1:])


def test_failed_receipt_withholds_measurement_and_api_is_read_only(tmp_path, monkeypatch):
    from bench.applied_trading import collection_projection
    name = "spot-ETHUSDT-20260915T140000Z"
    (tmp_path / name).mkdir()
    def reject(*_args, **_kwargs):
        raise ValueError("private body/path must not leak")
    monkeypatch.setattr(collection_projection, "project_known_collection", reject)
    app = FastAPI()
    register(app, root=tmp_path)
    client = TestClient(app)
    response = client.get("/api/applied_data_collection")
    assert response.status_code == 200
    result = response.json()
    assert result["batches"] == [{"id": name, "status": "invalid_receipt"}]
    assert result["status"] == "unavailable"
    assert "private body/path" not in response.text
    assert client.post("/api/applied_data_collection").status_code == 405
    assert list((tmp_path / name).iterdir()) == []


def test_historical_collector_source_is_not_misreported_as_corrupt(tmp_path, monkeypatch):
    from bench.applied_trading import collection_projection
    name = "spot-BTCUSDT-20260915T140000Z"
    (tmp_path / name).mkdir()
    monkeypatch.setattr(collection_projection, "project_known_collection", lambda _: {
        "collector_source_verified": False,
        "collector_source_status": "historical_source_unavailable",
        "status": "complete_incremental_batch", "requests_attempted": 3,
        "requests_succeeded": 3, "requests_failed": 0, "source_valid_frames": 3,
    })
    row = project_market_research(tmp_path)
    assert row["batches"][0]["collector_source_status"] == "historical_source_unavailable"
    assert row["batches"][0]["requests_attempted"] == 3
    assert row["status"] == "unavailable"
    assert row["stages"][0]["status"] == "not_recorded"
    assert row["warnings"] == []
