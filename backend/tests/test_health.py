from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["market"] == "IN"
    assert response.json()["category"] == "footwear"
    assert response.json()["product"] == "authenticity_verification"
