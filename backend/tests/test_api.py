from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_requirements_endpoint() -> None:
    response = client.post(
        "/v1/requirements",
        json={"query": "walking shoes under ₹10000 for a wide foot"},
    )

    assert response.status_code == 200
    data = response.json()["requirements"]
    assert data["budget_max_inr"] == 10000
    assert data["width"] == "wide"
