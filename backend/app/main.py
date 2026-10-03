from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from .image_quality import InvalidImageError
from .ocr import TesseractOCRProvider
from .vision import create_vision_provider
from .submissions import (
    MAX_PHOTOS,
    MAX_PHOTO_BYTES,
    MAX_TOTAL_UPLOAD_BYTES,
    LocalImageStorage,
    PhotoUpload,
    SQLiteSubmissionRepository,
    SubmissionMetadata,
    VerificationSubmissionService,
)
from .research import (
    BraveSearchClient,
    ProductResearchProvider,
    SearchConfigurationError,
    SearchProviderError,
)
from .evidence_engine import build_evidence_report
from .authenticity_engine import build_authenticity_assessment

app = FastAPI(title="Veyro Authenticity API", version="0.1.0")
cors_origins = [
    origin.strip()
    for origin in os.environ.get(
        "VEYRO_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
data_root = Path(os.environ.get("VEYRO_DATA_DIR", "var"))
app.state.submission_service = VerificationSubmissionService(
    storage=LocalImageStorage(data_root / "images"),
    repository=SQLiteSubmissionRepository(data_root / "submissions.sqlite3"),
    ocr_provider=TesseractOCRProvider(
        executable=os.environ.get("VEYRO_TESSERACT_CMD", "tesseract")
    ),
    vision_provider=create_vision_provider(),
)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "veyro",
        "market": "IN",
        "category": "footwear",
        "product": "authenticity_verification",
    }


@app.post("/v1/authenticity/checks", status_code=status.HTTP_201_CREATED)
def create_authenticity_submission(
    request: Request,
    metadata: str = Form(..., description="JSON listing metadata"),
    photos: list[UploadFile] = File(..., description="One or more footwear photos"),
) -> dict[str, object]:
    if not photos:
        raise HTTPException(status_code=422, detail="Upload at least one footwear photo")
    if len(photos) > MAX_PHOTOS:
        raise HTTPException(
            status_code=413, detail=f"Upload no more than {MAX_PHOTOS} photos"
        )
    try:
        submission_metadata = SubmissionMetadata.model_validate_json(metadata)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=error.errors()) from error

    uploads: list[PhotoUpload] = []
    total_bytes = 0
    try:
        for photo in photos:
            image_bytes = photo.file.read(MAX_PHOTO_BYTES + 1)
            if len(image_bytes) > MAX_PHOTO_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Each photo must be no larger than {MAX_PHOTO_BYTES // (1024 * 1024)} MB",
                )
            total_bytes += len(image_bytes)
            if total_bytes > MAX_TOTAL_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413, detail="Combined photo upload must not exceed 40 MB"
                )
            uploads.append(PhotoUpload(
                filename=photo.filename or "photo",
                image_bytes=image_bytes,
            ))
        result = request.app.state.submission_service.submit(
            submission_metadata, uploads
        )
    except InvalidImageError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        for photo in photos:
            photo.file.close()

    return result.model_dump(mode="json")


@app.post("/v1/authenticity/checks/{check_id}/identify")
def identify_submitted_product(check_id: str, request: Request) -> dict[str, object]:
    repository = request.app.state.submission_service.repository
    submission = repository.get(check_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Verification submission not found")
    provider = getattr(request.app.state, "product_identification_provider", None)
    if provider is None:
        try:
            provider = ProductResearchProvider(BraveSearchClient())
        except SearchConfigurationError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
    try:
        report = provider.identify(submission)
        repository.save_research_report(report)
        repository.save_evidence_report(build_evidence_report(submission, report))
    except SearchProviderError as error:
        raise HTTPException(status_code=502, detail="External product research is temporarily unavailable") from error
    return report.model_dump(mode="json")


@app.get("/v1/authenticity/checks/{check_id}/evidence")
def get_check_evidence(check_id: str, request: Request) -> dict[str, object]:
    repository = request.app.state.submission_service.repository
    submission = repository.get(check_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Verification submission not found")
    report = repository.get_evidence_report(check_id)
    if report is None:
        research_report = repository.get_research_report(check_id)
        report = build_evidence_report(submission, research_report)
        repository.save_evidence_report(report)
    return report.model_dump(mode="json")


@app.get("/v1/authenticity/checks/{check_id}/assessment")
def get_check_assessment(check_id: str, request: Request) -> dict[str, object]:
    repository = request.app.state.submission_service.repository
    submission = repository.get(check_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Verification submission not found")
    assessment = repository.get_assessment(check_id)
    if assessment is None:
        evidence_report = repository.get_evidence_report(check_id)
        if evidence_report is None:
            evidence_report = build_evidence_report(
                submission, repository.get_research_report(check_id)
            )
            repository.save_evidence_report(evidence_report)
        assessment = build_authenticity_assessment(submission, evidence_report)
        repository.save_assessment(assessment)
    return assessment.model_dump(mode="json")
