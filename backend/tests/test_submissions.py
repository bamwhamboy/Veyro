import json
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.domain import OCRExtraction, VerificationSubmission
from app.main import app
from app.submissions import (
    LocalImageStorage,
    SQLiteSubmissionRepository,
    VerificationSubmissionService,
)


def make_photo(*, detailed: bool = True, size: tuple[int, int] = (800, 600)) -> bytes:
    image = Image.new("RGB", size, "white")
    if detailed:
        ImageDraw.Draw(image).text(
            (40, 40),
            "NIKE MODEL: CT1234 SKU: N123-01 SIZE: US 9 COLOUR: BLACK",
            fill="black",
        )
    output = BytesIO()
    image.save(output, format="JPEG")
    return output.getvalue()


class OCRStub:
    provider_name = "test_ocr"

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def extract(self, image_path):
        assert image_path.exists()
        self.calls += 1
        return OCRExtraction(text=self.text, confidence=0.91)


def make_service(tmp_path, ocr=None):
    root = tmp_path / "data"
    return VerificationSubmissionService(
        storage=LocalImageStorage(root / "images"),
        repository=SQLiteSubmissionRepository(root / "submissions.sqlite3"),
        ocr_provider=ocr or OCRStub(
            "NIKE MODEL: CT1234 SKU: N123-01 SIZE: US 9 COLOUR: BLACK"
        ),
    )


def test_submission_uploads_multiple_images_and_persists_metadata(tmp_path) -> None:
    ocr = OCRStub("NIKE MODEL: CT1234 SKU: N123-01 SIZE: US 9 COLOUR: BLACK")
    service = make_service(tmp_path, ocr)
    from app.submissions import PhotoUpload, SubmissionMetadata

    submission = service.submit(
        SubmissionMetadata(listing_title="Running shoe"),
        [
            PhotoUpload("../label-one.jpg", make_photo()),
            PhotoUpload("label-two.jpg", make_photo()),
        ],
    )

    assert len(submission.photos) == 2
    assert ocr.calls == 2
    assert submission.candidate.brand == "Nike"
    assert submission.candidate.model_number == "CT1234"
    assert submission.candidate.sku == "N123-01"
    assert submission.candidate.size == "US 9"
    assert submission.candidate.confidence == 0.91
    assert submission.candidate.field_evidence_ids["model_number"]
    assert all(photo.filename == "label-one.jpg" or photo.filename == "label-two.jpg"
               for photo in submission.photos)

    repository = service.repository
    stored = repository.get(submission.check.check_id)
    assert isinstance(stored, VerificationSubmission)
    assert stored.check.listing_title == "Running shoe"
    assert len(stored.photos) == 2
    assert all(service.storage.path_for(photo.storage_key).is_file()
               for photo in stored.photos)


def test_submission_does_not_invent_values_when_ocr_has_no_identifiers(tmp_path) -> None:
    from app.submissions import PhotoUpload, SubmissionMetadata

    submission = make_service(tmp_path, OCRStub("sports footwear")).submit(
        SubmissionMetadata(), [PhotoUpload("photo.jpg", make_photo())]
    )

    assert submission.candidate.brand is None
    assert submission.candidate.model_number is None
    assert submission.candidate.size is None
    assert submission.candidate.evidence_ids == []
    assert submission.missing_identity_fields


def test_reports_poor_photo_quality(tmp_path) -> None:
    from app.submissions import PhotoUpload, SubmissionMetadata

    submission = make_service(tmp_path, OCRStub("")).submit(
        SubmissionMetadata(),
        [PhotoUpload("blurred.jpg", make_photo(detailed=False, size=(200, 200)))],
    )

    assert submission.photos[0].quality.status == "retake_recommended"
    assert "low_resolution" in submission.photos[0].quality.issues
    assert any("Photo 1 may need a retake" in item for item in submission.guidance)


def test_api_accepts_repeated_photo_uploads_and_metadata(tmp_path) -> None:
    app.state.submission_service = make_service(tmp_path)
    client = TestClient(app)
    payload = make_photo()
    response = client.post(
        "/v1/authenticity/checks",
        data={"metadata": json.dumps({"listing_title": "Running shoe"})},
        files=[
            ("photos", ("label.jpg", payload, "image/jpeg")),
            ("photos", ("sole.jpg", make_photo(size=(700, 600)), "image/jpeg")),
        ],
    )
    assert response.status_code == 201
    data = response.json()
    assert data["check"]["market"] == "IN"
    assert len(data["photos"]) == 2
    assert data["candidate"]["brand"] == "Nike"


def test_api_rejects_invalid_photo_content(tmp_path) -> None:
    app.state.submission_service = make_service(tmp_path)
    client = TestClient(app)
    response = client.post(
        "/v1/authenticity/checks",
        data={"metadata": "{}"},
        files=[("photos", ("not-a-photo.jpg", b"not an image", "image/jpeg"))],
    )
    assert response.status_code == 422


def test_unavailable_ocr_is_reported_without_inventing_identity(tmp_path) -> None:
    class MissingOCR:
        provider_name = "not-installed"

        def extract(self, image_path):
            raise FileNotFoundError

    from app.submissions import PhotoUpload, SubmissionMetadata

    submission = make_service(tmp_path, MissingOCR()).submit(
        SubmissionMetadata(), [PhotoUpload("label.jpg", make_photo())]
    )
    assert submission.photos[0].ocr_status == "unavailable"
    assert submission.candidate.brand is None
    assert submission.candidate.model_number is None
    assert any("remain unassessed" in item for item in submission.guidance)
