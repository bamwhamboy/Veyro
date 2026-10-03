import base64
import json

import pytest
from io import BytesIO
from PIL import Image
from fastapi.testclient import TestClient

from app.domain import AuthenticityCheck, OCRExtraction
from app.submissions import (
    LocalImageStorage,
    PhotoUpload,
    SQLiteSubmissionRepository,
    SubmissionMetadata,
    VerificationSubmissionService,
)
from app.main import app
from app.vision import OpenAIVisionProvider, VisionConfigurationError


def make_photo():
    output = BytesIO()
    Image.new("RGB", (640, 480), "white").save(output, format="JPEG")
    return output.getvalue()


class FakeResponses:
    def __init__(self, observations):
        self.observations = observations
        self.payload = None
        self.api_key = None

    def create(self, payload, *, api_key, timeout_seconds):
        self.payload = payload
        self.api_key = api_key
        return {"output": [{"type": "message", "content": [{
            "type": "output_text",
            "text": json.dumps({"observations": self.observations}),
        }]}]}


def test_openai_adapter_sends_image_and_returns_traceable_observations(tmp_path):
    image = tmp_path / "uploaded-id.jpg"
    image.write_bytes(b"jpeg bytes")
    transport = FakeResponses([
        {"attribute": "brand", "value": "Nike", "visual_basis": "NIKE wordmark on tongue", "confidence": 0.93},
        {"attribute": "style_code", "value": "CT1234-001", "visual_basis": "legible code on inner label", "confidence": 0.82},
        {"attribute": "packaging", "value": "Orange Nike shoebox", "visual_basis": "orange box and visible wordmark", "confidence": 0.88},
        {"attribute": "physical_observation", "value": "Black mesh upper with white sole", "visual_basis": "visible upper and midsole", "confidence": 0.90},
    ])
    provider = OpenAIVisionProvider(api_key="test-key", transport=transport)
    bundle = provider.analyze(AuthenticityCheck(image_urls=["upload://uploaded-id"]), image)

    assert transport.api_key == "test-key"
    assert transport.payload["model"] == "gpt-6-luna"
    image_input = transport.payload["input"][0]["content"][1]
    assert image_input["type"] == "input_image"
    assert image_input["image_url"] == "data:image/jpeg;base64," + base64.b64encode(b"jpeg bytes").decode()
    assert transport.payload["store"] is False
    assert {item.subject for item in bundle.evidence} == {
        "brand", "style_code", "packaging", "physical_observation"
    }
    assert all(item.confidence is not None and item.supporting_text for item in bundle.evidence)
    assert all(item.source_id == bundle.sources[0].source_id for item in bundle.evidence)
    assert bundle.sources[0].uri == "upload://uploaded-id"


def test_provider_uses_environment_key_and_configurable_model(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "environment-key")
    monkeypatch.setenv("OPENAI_VISION_MODEL", "gpt-6-luna")
    image = tmp_path / "shoe.webp"
    image.write_bytes(b"webp")
    transport = FakeResponses([])
    bundle = OpenAIVisionProvider(transport=transport).analyze(
        AuthenticityCheck(image_urls=["upload://shoe"]), image
    )
    assert transport.api_key == "environment-key"
    assert transport.payload["model"] == "gpt-6-luna"
    assert bundle.evidence == []


def test_provider_without_key_makes_no_request_or_observation(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    image = tmp_path / "shoe.jpg"
    image.write_bytes(b"image")
    transport = FakeResponses([])
    with pytest.raises(VisionConfigurationError):
        OpenAIVisionProvider(transport=transport).analyze(
            AuthenticityCheck(image_urls=["upload://shoe"]), image
        )
    assert transport.payload is None


def test_submission_merges_vision_identity_and_persists_evidence(tmp_path):
    class OCR:
        provider_name = "mock-ocr"

        def extract(self, image_path):
            return OCRExtraction(text="", confidence=None)

    transport = FakeResponses([
        {"attribute": "brand", "value": "ASICS", "visual_basis": "ASICS logo", "confidence": 0.91},
        {"attribute": "model", "value": "Gel-Kayano 31", "visual_basis": "printed model name on box", "confidence": 0.78},
        {"attribute": "sku", "value": "1011B867-001", "visual_basis": "code visible on label", "confidence": 0.85},
        {"attribute": "colourway", "value": "Black/Graphite Grey", "visual_basis": "visible shoe colours", "confidence": 0.87},
        {"attribute": "visible_label", "value": "US 9 / EU 42.5", "visual_basis": "size label", "confidence": 0.96},
        {"attribute": "visible_marking", "value": "GEL on midsole", "visual_basis": "letters on lateral midsole", "confidence": 0.94},
    ])
    root = tmp_path / "data"
    service = VerificationSubmissionService(
        storage=LocalImageStorage(root / "images"),
        repository=SQLiteSubmissionRepository(root / "submissions.sqlite3"),
        ocr_provider=OCR(),
        vision_provider=OpenAIVisionProvider(api_key="mock-key", transport=transport),
    )
    result = service.submit(SubmissionMetadata(), [PhotoUpload("shoe.jpg", make_photo())])
    stored = service.repository.get(result.check.check_id)

    assert result.candidate.brand == "ASICS"
    assert result.candidate.product_name == "Gel-Kayano 31"
    assert result.candidate.sku == "1011B867-001"
    assert result.candidate.colorway == "Black/Graphite Grey"
    assert result.candidate.field_evidence_ids["brand"]
    assert result.photos[0].vision_status == "complete"
    assert len(result.photos[0].vision_evidence_ids) == 6
    assert stored is not None
    assert len(stored.evidence_sources) == 1
    assert len(stored.evidence) == 6
    assert set(stored.photos[0].vision_evidence_ids) <= {item.evidence_id for item in stored.evidence}


def test_missing_vision_key_is_reported_without_fabricating_fields(tmp_path, monkeypatch):
    class OCR:
        provider_name = "mock-ocr"

        def extract(self, image_path):
            return OCRExtraction()

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    root = tmp_path / "data"
    service = VerificationSubmissionService(
        storage=LocalImageStorage(root / "images"),
        repository=SQLiteSubmissionRepository(root / "submissions.sqlite3"),
        ocr_provider=OCR(),
        vision_provider=OpenAIVisionProvider(),
    )
    result = service.submit(SubmissionMetadata(), [PhotoUpload("shoe.jpg", make_photo())])
    assert result.photos[0].vision_status == "unavailable"
    assert result.photos[0].vision_evidence_ids == []
    assert result.candidate.brand is None
    assert result.evidence == []
    assert any("selected vision provider API key" in text for text in result.guidance)


def test_submission_api_returns_mocked_visual_identity_and_evidence(tmp_path, monkeypatch):
    class OCR:
        provider_name = "mock-ocr"

        def extract(self, image_path):
            return OCRExtraction()

    transport = FakeResponses([
        {"attribute": "brand", "value": "Puma", "visual_basis": "PUMA wordmark on shoe", "confidence": 0.89},
        {"attribute": "visible_marking", "value": "NITRO on midsole", "visual_basis": "NITRO lettering on sole", "confidence": 0.81},
    ])
    root = tmp_path / "data"
    app.state.submission_service = VerificationSubmissionService(
        storage=LocalImageStorage(root / "images"),
        repository=SQLiteSubmissionRepository(root / "submissions.sqlite3"),
        ocr_provider=OCR(),
        vision_provider=OpenAIVisionProvider(api_key="mock-key", transport=transport),
    )
    from app.domain import ProductIdentificationReport

    class ResearchStub:
        def identify(self, submission):
            assert submission.candidate.brand == "Puma"
            assert submission.candidate.field_evidence_ids["brand"]
            return ProductIdentificationReport(
                check_id=submission.check.check_id,
                provider="mock-research",
                queries=["Puma visible shoe identity"],
            )

    monkeypatch.setattr(app.state, "product_identification_provider", ResearchStub(), raising=False)
    response = TestClient(app).post(
        "/v1/authenticity/checks",
        data={"metadata": "{}"},
        files=[("photos", ("shoe.jpg", make_photo(), "image/jpeg"))],
    )
    assert response.status_code == 201
    result = response.json()
    assert result["candidate"]["brand"] == "Puma"
    assert result["photos"][0]["vision_status"] == "complete"
    assert len(result["photos"][0]["vision_evidence_ids"]) == 2
    assert [item["subject"] for item in result["evidence"]] == ["brand", "visible_marking"]
    assert all(item["source_id"] == result["evidence_sources"][0]["source_id"] for item in result["evidence"])
    check_id = result["check"]["check_id"]
    client = TestClient(app)
    identified = client.post(f"/v1/authenticity/checks/{check_id}/identify")
    evidence = client.get(f"/v1/authenticity/checks/{check_id}/evidence")
    assessment = client.get(f"/v1/authenticity/checks/{check_id}/assessment")
    assert identified.status_code == evidence.status_code == assessment.status_code == 200
    assert any(item["exact_claim"] == "brand: Puma" for item in evidence.json()["evidence"])
    assert assessment.json()["overall_assessment"] == "inconclusive"
