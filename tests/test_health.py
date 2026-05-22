"""Smoke test, exercises the FastAPI app boots and answers /healthz.

A real CI run will also exercise the pipeline against the LAZ + GeoTIFF
fixtures under `tests/fixtures/`; the fixtures are gitignored for size
reasons and synthesised on demand by a separate helper.
"""

from fastapi.testclient import TestClient

from app.main import app


def test_healthz_returns_ok() -> None:
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == app.version


def test_index_advertises_docs_url() -> None:
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "helios-lidar"
    assert body["docs"].endswith("/docs")
