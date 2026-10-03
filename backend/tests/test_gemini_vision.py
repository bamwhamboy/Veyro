import base64
import json
from io import BytesIO

import pytest
from PIL import Image

from app.domain import AuthenticityCheck, OCRExtraction
from app.submissions import (
    LocalImageStorage,
    PhotoUpload,
    SQLiteSubmissionRepository,
    SubmissionMetadata,
    VerificationSubmissionService,
)
from app.vision import (
    GeminiVisionProvider,
    VisionConfigurationError,
    create_vision_provider,
)


def make_photo() -> bytes:
    image = BytesIO()
    Image.new("RGB", (640, 480), "white").save(image, format="JPEG")
    return image.getvalue()


class FakeGeminiTransport:
    def __init__(self, observations):
        self.observations = observations
        self.payload = None
        self.api_key = None

    def create(self, payload, *, api_key, timeout_seconds):
        self.payload = payload
        self.api_key = api_key
        return {
            "status": "completed",
            "steps": [{
                "type": "model_output",
                "content": [{
                    "type": "text",
                    "text": json.dumps({"observations": self.observations}),
                }],
            }],
        }


def observation(attribute, value, basis="clearly visible marking", confidence=0.87):
    return {
        "attribute": attribute,
        "value": value,
        "visual_basis": basis,
        "confidence": confidence,
    }


def test_gemini_provider_sends_image_with_schema_and_normalizes_observations(tmp_path):
    image_path = tmp_path / "label-image.webp"
    image_path.write_bytes(b"webp bytes")
    transport = FakeGeminiTransport([
        observation("brand", "New Balance", "N logo and New Balance text", 0.93),
        observation("model", "990v6", "model name visible on box", 0.81),
        observation("sku", "U990TG6", "code clearly printed on product label", 0.88),
        observation("style_code", "U990TG6", "same code on label", 0.86),
        observation("colourway", "Grey/Silver", "visible shoe colours", 0.84),
        observation("size", "US 9", "size label is legible", 0.92),
        observation("visible_label", "Made in USA", "text visible on heel label", 0.79),
        observation("packaging", "White shoe box with NB logo"),
        observation("visible_marking", "N on lateral side"),
        observation("physical_observation", "Grey suede and mesh upper"),
        observation("physical_observation", "unreadable", "no legible text", 0.1),
    ])
    provider = GeminiVisionProvider(api_key="mock-gemini-key", transport=transport)
    bundle = provider.analyze(
        AuthenticityCheck(image_urls=["upload://label-image"]), image_path
    )

    assert transport.api_key == "mock-gemini-key"
    assert transport.payload["model"] == "gemini-3.1-flash-lite"
    text_part, image_part = transport.payload["input"]
    assert text_part["type"] == "text"
    assert image_part == {
        "type": "image",
        "mime_type": "image/webp",
        "data": base64.b64encode(b"webp bytes").decode("ascii"),
    }
    assert transport.payload["response_format"]["mime_type"] == "application/json"
    assert transport.payload["response_format"]["schema"]["properties"]["observations"]
    assert {item.subject for item in bundle.evidence} == {
        "brand", "product_name", "sku", "style_code", "colorway", "size",
        "label_info", "packaging", "visible_marking", "physical_observation",
    }
    assert all(item.confidence is not None and item.supporting_text for item in bundle.evidence)
    assert all(item.source_url == "upload://label-image" for item in bundle.evidence)
    assert len(bundle.evidence) == 10


def test_gemini_reads_environment_key_and_model_and_omits_empty_observations(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "environment-key")
    monkeypatch.setenv("GEMINI_VISION_MODEL", "gemini-3.1-flash-lite")
    image_path = tmp_path / "photo.jpg"
    image_path.write_bytes(b"jpeg")
    transport = FakeGeminiTransport([
        observation("brand", "not visible"),
        observation("model", "", "nothing readable"),
    ])

    bundle = GeminiVisionProvider(transport=transport).analyze(
        AuthenticityCheck(image_urls=["upload://photo"]), image_path
    )
    assert transport.api_key == "environment-key"
    assert transport.payload["model"] == "gemini-3.1-flash-lite"
    assert bundle.evidence == []


def test_gemini_missing_key_does_not_call_transport(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    image_path = tmp_path / "photo.jpg"
    image_path.write_bytes(b"jpeg")
    transport = FakeGeminiTransport([])

    with pytest.raises(VisionConfigurationError, match="GEMINI_API_KEY"):
        GeminiVisionProvider(transport=transport).analyze(
            AuthenticityCheck(image_urls=["upload://photo"]), image_path
        )
    assert transport.payload is None


def test_provider_selection_defaults_to_gemini_and_preserves_openai(monkeypatch):
    monkeypatch.delenv("VISION_PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert isinstance(create_vision_provider(), GeminiVisionProvider)
    assert type(create_vision_provider("openai")).__name__ == "OpenAIVisionProvider"
    monkeypatch.setenv("VISION_PROVIDER", "openai")
    assert type(create_vision_provider()).__name__ == "OpenAIVisionProvider"
    monkeypatch.setenv("VISION_PROVIDER", "unsupported")
    with pytest.raises(ValueError, match="VISION_PROVIDER"):
        create_vision_provider()


def test_gemini_provider_integrates_with_submission_identity_pipeline(tmp_path):
    class OCRStub:
        provider_name = "mock-ocr"

        def extract(self, image_path):
            return OCRExtraction()

    root = tmp_path / "data"
    transport = FakeGeminiTransport([
        observation("brand", "Adidas", "three stripes mark", 0.9),
        observation("style_code", "ID1234", "style code on tongue label", 0.84),
    ])
    service = VerificationSubmissionService(
        storage=LocalImageStorage(root / "images"),
        repository=SQLiteSubmissionRepository(root / "submissions.sqlite3"),
        ocr_provider=OCRStub(),
        vision_provider=GeminiVisionProvider(api_key="test-key", transport=transport),
    )

    submission = service.submit(
        SubmissionMetadata(), [PhotoUpload("shoe.jpg", make_photo())]
    )
    stored = service.repository.get(submission.check.check_id)
    assert submission.candidate.brand == "Adidas"
    assert submission.candidate.style_code == "ID1234"
    assert submission.candidate.field_evidence_ids["brand"]
    assert submission.photos[0].vision_status == "complete"
    assert stored is not None and stored.evidence == submission.evidence
