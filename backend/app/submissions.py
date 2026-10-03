"""Submission processing, image storage, OCR field extraction, and persistence."""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path, PurePosixPath
import sqlite3
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .domain import (
    AuthenticityCheck,
    AuthenticityAssessment,
    Evidence,
    EvidenceSource,
    EvidenceReport,
    ImageQualityReport,
    ProductIdentity,
    ProductIdentificationReport,
    SubmittedPhoto,
    VerificationSubmission,
)
from .identity_extraction import extract_identity, extract_visual_identity, merge_identity_candidates
from .image_quality import InvalidImageError, inspect_uploaded_image
from .ocr import OCRProviderError
from .providers import OCRProvider, VisionProvider
from .vision import VisionConfigurationError, VisionProviderError

logger = logging.getLogger(__name__)

MAX_PHOTOS = 8
MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_TOTAL_UPLOAD_BYTES = 40 * 1024 * 1024


class SubmissionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    listing_title: str | None = None
    listing_url: str | None = None
    seller_name: str | None = None


@dataclass(frozen=True)
class PhotoUpload:
    filename: str
    image_bytes: bytes


class ImageStorage(Protocol):
    def save(
        self, check_id: str, image_id: str, extension: str, image_bytes: bytes
    ) -> str: ...

    def path_for(self, storage_key: str) -> Path: ...

    def delete(self, storage_key: str) -> None: ...


class SubmissionRepository(Protocol):
    def save(self, submission: VerificationSubmission) -> None: ...

    def get(self, check_id: str) -> VerificationSubmission | None: ...

    def save_research_report(self, report: ProductIdentificationReport) -> None: ...

    def get_research_report(self, check_id: str) -> ProductIdentificationReport | None: ...

    def save_evidence_report(self, report: EvidenceReport) -> None: ...

    def get_evidence_report(self, check_id: str) -> EvidenceReport | None: ...

    def save_assessment(self, assessment: AuthenticityAssessment) -> None: ...

    def get_assessment(self, check_id: str) -> AuthenticityAssessment | None: ...


class LocalImageStorage:
    """Local filesystem storage; use a mounted persistent volume in deployment."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def save(
        self, check_id: str, image_id: str, extension: str, image_bytes: bytes
    ) -> str:
        relative = PurePosixPath(check_id) / f"{image_id}.{extension}"
        destination = self.root / Path(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        try:
            temporary.write_bytes(image_bytes)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return relative.as_posix()

    def path_for(self, storage_key: str) -> Path:
        relative = PurePosixPath(storage_key)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Invalid image storage key")
        return self.root / Path(*relative.parts)

    def delete(self, storage_key: str) -> None:
        self.path_for(storage_key).unlink(missing_ok=True)


class SQLiteSubmissionRepository:
    """Stores submission metadata and OCR output as JSON in SQLite."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def save(self, submission: VerificationSubmission) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        payload = submission.model_dump_json()
        with sqlite3.connect(self.database_path, timeout=10) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS submissions (
                    check_id TEXT PRIMARY KEY,
                    submitted_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )"""
            )
            connection.execute(
                "INSERT INTO submissions (check_id, submitted_at, payload) VALUES (?, ?, ?)",
                (
                    submission.check.check_id,
                    submission.check.submitted_at.isoformat(),
                    payload,
                ),
            )

    def get(self, check_id: str) -> VerificationSubmission | None:
        if not self.database_path.exists():
            return None
        with sqlite3.connect(self.database_path, timeout=10) as connection:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='submissions'"
            ).fetchone()
            if table is None:
                return None
            row = connection.execute(
                "SELECT payload FROM submissions WHERE check_id = ?", (check_id,)
            ).fetchone()
        return VerificationSubmission.model_validate_json(row[0]) if row else None

    def save_research_report(self, report: ProductIdentificationReport) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path, timeout=10) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS research_reports (
                    check_id TEXT PRIMARY KEY,
                    queried_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )"""
            )
            connection.execute(
                "INSERT OR REPLACE INTO research_reports (check_id, queried_at, payload) VALUES (?, ?, ?)",
                (report.check_id, report.queried_at.isoformat(), report.model_dump_json()),
            )

    def get_research_report(self, check_id: str) -> ProductIdentificationReport | None:
        if not self.database_path.exists():
            return None
        with sqlite3.connect(self.database_path, timeout=10) as connection:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_reports'"
            ).fetchone()
            if table is None:
                return None
            row = connection.execute(
                "SELECT payload FROM research_reports WHERE check_id = ?", (check_id,)
            ).fetchone()
        return ProductIdentificationReport.model_validate_json(row[0]) if row else None

    def save_evidence_report(self, report: EvidenceReport) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path, timeout=10) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS evidence_reports (
                    check_id TEXT PRIMARY KEY,
                    generated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )"""
            )
            connection.execute(
                "INSERT OR REPLACE INTO evidence_reports (check_id, generated_at, payload) VALUES (?, ?, ?)",
                (report.check_id, report.generated_at.isoformat(), report.model_dump_json()),
            )
            assessment_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='authenticity_assessments'"
            ).fetchone()
            if assessment_table:
                connection.execute(
                    "DELETE FROM authenticity_assessments WHERE check_id = ?", (report.check_id,)
                )

    def get_evidence_report(self, check_id: str) -> EvidenceReport | None:
        if not self.database_path.exists():
            return None
        with sqlite3.connect(self.database_path, timeout=10) as connection:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='evidence_reports'"
            ).fetchone()
            if table is None:
                return None
            row = connection.execute(
                "SELECT payload FROM evidence_reports WHERE check_id = ?", (check_id,)
            ).fetchone()
        return EvidenceReport.model_validate_json(row[0]) if row else None

    def save_assessment(self, assessment: AuthenticityAssessment) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path, timeout=10) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS authenticity_assessments (
                    check_id TEXT PRIMARY KEY,
                    assessed_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )"""
            )
            connection.execute(
                "INSERT OR REPLACE INTO authenticity_assessments (check_id, assessed_at, payload) VALUES (?, ?, ?)",
                (assessment.check_id, assessment.assessed_at.isoformat(), assessment.model_dump_json()),
            )

    def get_assessment(self, check_id: str) -> AuthenticityAssessment | None:
        if not self.database_path.exists():
            return None
        with sqlite3.connect(self.database_path, timeout=10) as connection:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='authenticity_assessments'"
            ).fetchone()
            if table is None:
                return None
            row = connection.execute(
                "SELECT payload FROM authenticity_assessments WHERE check_id = ?", (check_id,)
            ).fetchone()
        return AuthenticityAssessment.model_validate_json(row[0]) if row else None


class VerificationSubmissionService:
    def __init__(
        self,
        *,
        storage: ImageStorage,
        repository: SubmissionRepository,
        ocr_provider: OCRProvider,
        vision_provider: VisionProvider | None = None,
    ) -> None:
        self.storage = storage
        self.repository = repository
        self.ocr_provider = ocr_provider
        self.vision_provider = vision_provider

    def submit(
        self, metadata: SubmissionMetadata, uploads: list[PhotoUpload]
    ) -> VerificationSubmission:
        if not uploads:
            raise ValueError("Upload at least one footwear photo")
        if len(uploads) > MAX_PHOTOS:
            raise ValueError(f"Upload no more than {MAX_PHOTOS} photos")
        if any(not upload.image_bytes for upload in uploads):
            raise ValueError("Uploaded photos cannot be empty")
        if any(len(upload.image_bytes) > MAX_PHOTO_BYTES for upload in uploads):
            raise ValueError(f"Each photo must be no larger than {MAX_PHOTO_BYTES // (1024 * 1024)} MB")
        if sum(len(upload.image_bytes) for upload in uploads) > MAX_TOTAL_UPLOAD_BYTES:
            raise ValueError("The combined photo upload must be no larger than 40 MB")

        inspected: list[tuple[PhotoUpload, str, ImageQualityReport]] = []
        for upload in uploads:
            try:
                media_type, quality = inspect_uploaded_image(upload.image_bytes)
            except InvalidImageError as error:
                safe_filename = Path(upload.filename.replace("\\", "/")).name or "photo"
                raise InvalidImageError(f"{safe_filename}: {error}") from error
            inspected.append((upload, media_type, quality))

        check_id = str(uuid4())
        image_ids = [str(uuid4()) for _ in inspected]
        check = AuthenticityCheck(
            check_id=check_id,
            **metadata.model_dump(),
            image_urls=[f"upload://{image_id}" for image_id in image_ids],
        )
        saved_keys: list[str] = []
        photos: list[SubmittedPhoto] = []
        evidence_sources: list[EvidenceSource] = []
        evidence: list[Evidence] = []
        candidates: list[ProductIdentity] = []

        try:
            for image_id, (upload, media_type, quality) in zip(image_ids, inspected):
                extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[media_type]
                safe_filename = Path(upload.filename.replace("\\", "/")).name or "photo"
                storage_key = self.storage.save(
                    check_id, image_id, extension, upload.image_bytes
                )
                saved_keys.append(storage_key)
                try:
                    extraction = self.ocr_provider.extract(self.storage.path_for(storage_key))
                    ocr_status: Literal["complete", "unavailable", "failed"] = "complete"
                    provider_message = None
                except FileNotFoundError:
                    extraction = None
                    ocr_status = "unavailable"
                    provider_message = "OCR provider is not installed or configured"
                except OCRProviderError:
                    logger.exception("OCR provider failed for image %s", image_id)
                    extraction = None
                    ocr_status = "failed"
                    provider_message = "OCR could not process this photo"
                except Exception:
                    logger.exception("Unexpected OCR provider error for image %s", image_id)
                    extraction = None
                    ocr_status = "failed"
                    provider_message = "OCR could not process this photo"

                text = extraction.text.strip() if extraction else ""
                confidence = extraction.confidence if extraction else None
                vision_bundle = None
                vision_status: Literal["complete", "unavailable", "failed"] = "unavailable"
                vision_message = "Vision provider is not configured"
                if self.vision_provider is not None:
                    try:
                        vision_bundle = self.vision_provider.analyze(
                            check, self.storage.path_for(storage_key)
                        )
                        vision_status = "complete"
                        vision_message = None
                    except VisionConfigurationError:
                        vision_message = "Vision unavailable; configure the selected provider API key"
                    except VisionProviderError:
                        logger.exception("Vision provider failed for image %s", image_id)
                        vision_status = "failed"
                        vision_message = "Vision could not analyze this photo"
                    except Exception:
                        logger.exception("Unexpected vision provider error for image %s", image_id)
                        vision_status = "failed"
                        vision_message = "Vision could not analyze this photo"

                photo_vision_ids = [item.evidence_id for item in vision_bundle.evidence] if vision_bundle else []
                if vision_bundle:
                    evidence_sources.extend(vision_bundle.sources)
                    evidence.extend(vision_bundle.evidence)
                    visual_candidate = extract_visual_identity(vision_bundle.evidence)
                    if visual_candidate.evidence_ids:
                        candidates.append(visual_candidate)

                photos.append(SubmittedPhoto(
                        image_id=image_id,
                        filename=safe_filename,
                        content_type=media_type,
                        size_bytes=len(upload.image_bytes),
                        storage_key=storage_key,
                        quality=quality,
                        ocr_status=ocr_status,
                        ocr_text=text,
                        ocr_confidence=confidence,
                        provider_message=provider_message,
                        vision_status=vision_status,
                        vision_message=vision_message,
                        vision_evidence_ids=photo_vision_ids,
                    ))
                if not text:
                    continue

                source = EvidenceSource(
                    source_type="ocr_output",
                    provider=self.ocr_provider.provider_name,
                    uri=storage_key,
                )
                evidence_sources.append(source)
                raw_evidence = Evidence(
                    source_id=source.source_id,
                    evidence_type="text_observation",
                    subject="ocr_text",
                    observation=f"OCR extracted text: {text}",
                    exact_claim=f"OCR extracted text: {text}",
                    supporting_text=text,
                    confidence=confidence,
                )
                evidence.append(raw_evidence)
                candidate, field_evidence = extract_identity(
                    text, confidence=confidence, source_id=source.source_id,
                    raw_evidence_id=raw_evidence.evidence_id,
                )
                candidates.append(candidate)
                evidence.extend(field_evidence)

            candidate, conflicts = merge_identity_candidates(candidates, evidence)
            missing_fields = [
                field for field, present in (
                    ("brand", candidate.brand),
                    ("model", candidate.product_name or candidate.model_number),
                    ("size", candidate.size),
                    ("colorway", candidate.colorway),
                ) if present is None
            ]
            if candidate.sku is None and candidate.style_code is None:
                missing_fields.append("sku_or_style_code")

            guidance: list[str] = []
            for index, photo in enumerate(photos, start=1):
                if photo.quality.issues:
                    guidance.append(
                        f"Photo {index} may need a retake: "
                        + ", ".join(photo.quality.issues)
                    )
            ocr_completed = any(photo.ocr_status == "complete" for photo in photos)
            vision_completed = any(photo.vision_status == "complete" for photo in photos)
            if missing_fields and (ocr_completed or vision_completed):
                guidance.append(
                    "No readable value was found for "
                    + ", ".join(missing_fields)
                    + ". If available, add a clear close-up of the shoe label."
                )
            if not ocr_completed and not vision_completed and all(
                photo.ocr_status == "unavailable" for photo in photos
            ) and all(photo.vision_status == "unavailable" for photo in photos):
                guidance.append(
                    "OCR and vision were unavailable; install Tesseract and configure "
                    "the selected vision provider API key. Identity fields remain unassessed."
                )
            elif not ocr_completed and not vision_completed:
                guidance.append(
                    "OCR and vision could not analyze any photos; identity fields remain unassessed."
                )
            if not vision_completed and all(photo.vision_status == "unavailable" for photo in photos):
                guidance.append(
                    "Image analysis was unavailable; configure the selected vision provider API key."
                )
            if conflicts:
                guidance.append(
                    "Different photos produced conflicting values for "
                    + ", ".join(conflicts)
                    + "; those fields were left unset."
                )

            submission = VerificationSubmission(
                check=check,
                candidate=candidate,
                photos=photos,
                evidence_sources=evidence_sources,
                evidence=evidence,
                missing_identity_fields=missing_fields,
                conflicting_fields=conflicts,
                guidance=guidance,
            )
            self.repository.save(submission)
            return submission
        except Exception:
            for storage_key in saved_keys:
                try:
                    self.storage.delete(storage_key)
                except OSError:
                    logger.exception("Could not clean up stored image %s", storage_key)
            raise
