from app.main import app
from app.submissions import SQLiteSubmissionRepository
from fastapi.testclient import TestClient
from types import SimpleNamespace


def test_submission_endpoint_is_exposed_and_shopping_endpoints_are_removed() -> None:
    paths = {route.path for route in app.routes}
    assert "/v1/requirements" not in paths
    assert "/v1/research" not in paths
    assert "/v1/authenticity/checks" in paths
    assert "/v1/authenticity/checks/{check_id}/identify" in paths
    assert "/v1/authenticity/checks/{check_id}/evidence" in paths
    assert "/v1/authenticity/checks/{check_id}/assessment" in paths


def test_evidence_endpoint_returns_and_persists_not_yet_checked_report(tmp_path, monkeypatch) -> None:
    from tests.test_evidence_engine import make_submission

    repository = SQLiteSubmissionRepository(tmp_path / "api.sqlite3")
    submission = make_submission(sku="ABC123")
    repository.save(submission)
    monkeypatch.setattr(app.state, "submission_service", SimpleNamespace(repository=repository))

    with TestClient(app) as client:
        response = client.get(f"/v1/authenticity/checks/{submission.check.check_id}/evidence")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "not_yet_checked"
    assert next(item for item in payload["comparisons"] if item["dimension"] == "sku")["evidence_status"] == "not_yet_checked"
    assert repository.get_evidence_report(submission.check.check_id) is not None


def test_assessment_endpoint_returns_and_persists_categorical_report(tmp_path, monkeypatch) -> None:
    from tests.test_evidence_engine import make_submission

    repository = SQLiteSubmissionRepository(tmp_path / "assessment-api.sqlite3")
    submission = make_submission(sku="ABC123")
    repository.save(submission)
    monkeypatch.setattr(app.state, "submission_service", SimpleNamespace(repository=repository))

    with TestClient(app) as client:
        response = client.get(f"/v1/authenticity/checks/{submission.check.check_id}/assessment")

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_assessment"] == "inconclusive"
    assert payload["confidence"] == "low"
    assert all(finding["evidence_ids"] for finding in payload["missing_evidence"])
    assert repository.get_assessment(submission.check.check_id) is not None
