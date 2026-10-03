"""Replaceable interfaces for the authenticity verification pipeline.

Sprint 0 intentionally defines contracts only. Concrete search, OCR, vision,
and brand-catalogue integrations are added in later sprints.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Protocol

from .domain import (
    AssessmentDecision,
    AuthenticityCheck,
    Evidence,
    EvidenceBundle,
    EvidenceComparison,
    EvidenceReport,
    ImageQualityReport,
    OCRExtraction,
    ProductIdentity,
    IdentificationResult,
    ProductIdentificationReport,
    VerificationSubmission,
)


class ProductIdentificationProvider(Protocol):
    def identify(self, check: AuthenticityCheck) -> IdentificationResult: ...


class SubmissionProductIdentificationProvider(Protocol):
    """Research external references for an already processed footwear submission."""

    def identify(self, submission: VerificationSubmission) -> ProductIdentificationReport: ...


class EvidenceProvider(Protocol):
    provider_kind: str

    def collect(
        self, check: AuthenticityCheck, identity: ProductIdentity
    ) -> EvidenceBundle: ...


class WebSearchProvider(EvidenceProvider, Protocol):
    provider_kind: Literal["web_search"]


class OCRProvider(Protocol):
    provider_name: str

    def extract(self, image_path: Path) -> OCRExtraction: ...


class VisionProvider(Protocol):
    provider_name: str

    def analyze(
        self, check: AuthenticityCheck, image_path: Path
    ) -> EvidenceBundle: ...


class ImageQualityProvider(Protocol):
    def inspect(self, image_bytes: bytes) -> ImageQualityReport: ...


class BrandCatalogueProvider(EvidenceProvider, Protocol):
    provider_kind: Literal["brand_catalogue"]


class EvidenceComparisonProvider(Protocol):
    def compare(
        self, identity: ProductIdentity, evidence: list[Evidence]
    ) -> list[EvidenceComparison]: ...


class EvidenceEngineProvider(Protocol):
    def build_report(self, submission: VerificationSubmission, research_report: ProductIdentificationReport | None) -> EvidenceReport: ...


class AuthenticityAssessmentProvider(Protocol):
    def assess(
        self,
        identity: ProductIdentity,
        evidence: list[Evidence],
        comparisons: list[EvidenceComparison],
    ) -> AssessmentDecision: ...
