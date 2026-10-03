"""Sprint 0 domain models for evidence-based footwear authenticity checks."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


def _new_id() -> str:
    return str(uuid4())


class AuthenticityCheck(BaseModel):
    """User submission that starts a verification; supplied fields are unverified."""

    check_id: str = Field(default_factory=_new_id)
    market: Literal["IN"] = "IN"
    category: Literal["footwear"] = "footwear"
    listing_title: str | None = None
    listing_url: str | None = None
    seller_name: str | None = None
    image_urls: list[str] = Field(default_factory=list)
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def submission_has_material(self) -> AuthenticityCheck:
        if not (self.listing_title or self.listing_url or self.image_urls):
            raise ValueError("Provide a listing title, listing URL, or at least one product image")
        return self


class ProductIdentity(BaseModel):
    """Candidate identity; values are not assertions of authenticity."""

    brand: str | None = None
    product_name: str | None = None
    model_number: str | None = None
    sku: str | None = None
    style_code: str | None = None
    size: str | None = None
    colorway: str | None = None
    other_identifiers: dict[str, str] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    field_confidence: dict[str, float] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    field_evidence_ids: dict[str, list[str]] = Field(default_factory=dict)


class EvidenceSource(BaseModel):
    source_id: str = Field(default_factory=_new_id)
    source_type: Literal[
        "user_listing", "user_image", "web_page", "brand_catalogue",
        "retailer_listing", "ocr_output", "vision_output", "official_brand",
        "authorised_retailer", "established_marketplace", "other_web",
    ]
    trust_level: Literal["very_high", "high", "medium", "low", "unrated"] = "unrated"
    provider: str = Field(min_length=1)
    uri: str | None = None
    market: Literal["IN"] = "IN"
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Evidence(BaseModel):
    evidence_id: str = Field(default_factory=_new_id)
    source_id: str
    evidence_type: Literal[
        "listing_field", "text_observation", "visual_observation",
        "catalogue_attribute", "serial_lookup",
    ]
    subject: str = Field(min_length=1)
    observation: str = Field(min_length=1)
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    exact_claim: str | None = None
    source_url: str | None = None
    retrieved_at: datetime | None = None
    provider: str | None = None
    supporting_text: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source_trust_level: Literal["very_high", "high", "medium", "low", "unrated"] | None = None
    derived_from_evidence_ids: list[str] = Field(default_factory=list)


class EvidenceBundle(BaseModel):
    sources: list[EvidenceSource] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def sources_exist_and_ids_are_unique(self) -> EvidenceBundle:
        source_ids = [source.source_id for source in self.sources]
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Evidence source IDs must be unique")
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("Evidence IDs must be unique")
        unknown_sources = {item.source_id for item in self.evidence} - set(source_ids)
        if unknown_sources:
            raise ValueError(f"Evidence references unknown sources: {sorted(unknown_sources)}")
        if {ref for item in self.evidence for ref in item.derived_from_evidence_ids} - set(evidence_ids):
            raise ValueError("Derived evidence references must resolve to included evidence")
        return self


class IdentityFieldComparison(BaseModel):
    field: str = Field(min_length=1)
    submitted_value: str | None = None
    researched_value: str | None = None
    result: Literal["match", "contradiction", "not_observed"]
    evidence_ids: list[str] = Field(default_factory=list)


class ProductIdentityCandidate(BaseModel):
    identity: ProductIdentity
    confidence: float = Field(ge=0.0, le=1.0)
    comparisons: list[IdentityFieldComparison] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class ProductIdentificationReport(BaseModel):
    check_id: str
    provider: str
    market: Literal["IN"] = "IN"
    queried_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    queries: list[str] = Field(default_factory=list)
    candidates: list[ProductIdentityCandidate] = Field(default_factory=list)
    evidence_sources: list[EvidenceSource] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def references_resolve(self) -> ProductIdentificationReport:
        source_ids = {source.source_id for source in self.evidence_sources}
        evidence_ids = {item.evidence_id for item in self.evidence}
        if len(source_ids) != len(self.evidence_sources) or len(evidence_ids) != len(self.evidence):
            raise ValueError("Evidence IDs must be unique")
        if any(item.source_id not in source_ids for item in self.evidence):
            raise ValueError("Every research evidence item must reference an included source")
        if {ref for item in self.evidence for ref in item.derived_from_evidence_ids} - evidence_ids:
            raise ValueError("Derived research evidence must reference included evidence")
        if any(set(candidate.evidence_ids) - evidence_ids for candidate in self.candidates):
            raise ValueError("Candidates must reference included evidence")
        for candidate in self.candidates:
            candidate_refs = set(candidate.identity.evidence_ids)
            candidate_refs.update(ref for refs in candidate.identity.field_evidence_ids.values() for ref in refs)
            if candidate_refs - evidence_ids:
                raise ValueError("Candidate identity must reference included evidence")
            refs = {ref for comparison in candidate.comparisons for ref in comparison.evidence_ids}
            if refs - evidence_ids:
                raise ValueError("Comparisons must reference included evidence")
        return self


class EvidenceComparison(BaseModel):
    comparison_id: str = Field(default_factory=_new_id)
    dimension: str = Field(min_length=1)
    result: Literal["match", "mismatch", "unknown", "insufficient_evidence"]
    explanation: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_status: Literal[
        "not_found", "contradicted", "not_yet_checked", "insufficient_evidence"
    ] | None = None
    submitted_value: str | None = None
    external_value: str | None = None
    source_trust_level: Literal["very_high", "high", "medium", "low", "unrated"] | None = None
    conflicting_evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def absence_is_not_a_mismatch(self) -> EvidenceComparison:
        if self.evidence_status in {"not_found", "not_yet_checked"} and self.result != "unknown":
            raise ValueError("Not-found and not-yet-checked comparisons must remain unknown")
        if self.evidence_status == "contradicted" and self.result != "mismatch":
            raise ValueError("Contradicted comparisons must be explicit mismatches")
        if self.evidence_status == "insufficient_evidence" and self.result != "insufficient_evidence":
            raise ValueError("Insufficient evidence status must use the insufficient_evidence result")
        return self


class EvidenceReport(BaseModel):
    check_id: str
    status: Literal["complete", "not_yet_checked"]
    evidence_sources: list[EvidenceSource] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    comparisons: list[EvidenceComparison] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def trace_is_complete(self) -> EvidenceReport:
        source_ids = {source.source_id for source in self.evidence_sources}
        evidence_ids = {item.evidence_id for item in self.evidence}
        if len(source_ids) != len(self.evidence_sources) or len(evidence_ids) != len(self.evidence):
            raise ValueError("Evidence and source IDs must be unique")
        if any(item.source_id not in source_ids for item in self.evidence):
            raise ValueError("Every evidence record must reference a report source")
        if {ref for item in self.evidence for ref in item.derived_from_evidence_ids} - evidence_ids:
            raise ValueError("Derived evidence references must resolve to report evidence")
        for comparison in self.comparisons:
            if (set(comparison.evidence_ids) | set(comparison.conflicting_evidence_ids)) - evidence_ids:
                raise ValueError("Every comparison reference must resolve to report evidence")
        return self


class AssessmentClaim(BaseModel):
    claim_id: str = Field(default_factory=_new_id)
    statement: str = Field(min_length=1)
    direction: Literal["supports_authenticity", "raises_concern", "neutral"]
    evidence_ids: list[str] = Field(min_length=1)


AuthenticityVerdict = Literal[
    "likely_authentic", "likely_counterfeit", "inconclusive", "insufficient_evidence"
]


class AssessmentDecision(BaseModel):
    """Conclusion returned by an assessor; evidence links are checked at assembly."""

    verdict: AuthenticityVerdict
    outcome_evidence_ids: list[str] = Field(min_length=1)
    claims: list[AssessmentClaim] = Field(default_factory=list)


class AssessmentFinding(BaseModel):
    finding_id: str = Field(default_factory=_new_id)
    dimension: str = Field(min_length=1)
    classification: Literal[
        "supporting", "concerning", "contradictory", "unknown", "insufficient_evidence"
    ]
    statement: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    source_trust_level: Literal["very_high", "high", "medium", "low", "unrated"] | None = None


class AuthenticityAssessment(BaseModel):
    """Rule-based explainable assessment; confidence is qualitative, not probability."""

    assessment_id: str = Field(default_factory=_new_id)
    check_id: str
    overall_assessment: Literal["likely_authentic", "likely_counterfeit", "inconclusive"]
    confidence: Literal["low", "moderate", "high"]
    confidence_basis: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    supporting_findings: list[AssessmentFinding] = Field(default_factory=list)
    concerns: list[AssessmentFinding] = Field(default_factory=list)
    contradictions: list[AssessmentFinding] = Field(default_factory=list)
    missing_evidence: list[AssessmentFinding] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_sources: list[EvidenceSource] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    comparisons: list[EvidenceComparison] = Field(default_factory=list)
    assessed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    identity: ProductIdentity = Field(default_factory=ProductIdentity)

    @model_validator(mode="after")
    def all_findings_resolve_to_evidence(self) -> AuthenticityAssessment:
        source_ids = {source.source_id for source in self.evidence_sources}
        evidence_ids = {item.evidence_id for item in self.evidence}
        if len(source_ids) != len(self.evidence_sources) or len(evidence_ids) != len(self.evidence):
            raise ValueError("Assessment evidence and source IDs must be unique")
        if any(item.source_id not in source_ids for item in self.evidence):
            raise ValueError("Assessment evidence must reference an included source")
        if {ref for item in self.evidence for ref in item.derived_from_evidence_ids} - evidence_ids:
            raise ValueError("Derived assessment evidence must reference included evidence")
        buckets = (
            (self.supporting_findings, "supporting"),
            (self.concerns, "concerning"),
            (self.contradictions, "contradictory"),
        )
        findings = [finding for group in (self.supporting_findings, self.concerns,
                     self.contradictions, self.missing_evidence) for finding in group]
        if any(finding.classification != classification for group, classification in buckets for finding in group):
            raise ValueError("Assessment finding classification does not match its report section")
        if any(finding.classification not in {"unknown", "insufficient_evidence"} for finding in self.missing_evidence):
            raise ValueError("Missing evidence findings must be unknown or insufficient_evidence")
        refs = set(self.evidence_ids)
        refs.update(self.identity.evidence_ids)
        refs.update(ref for values in self.identity.field_evidence_ids.values() for ref in values)
        refs.update(ref for finding in findings for ref in finding.evidence_ids)
        refs.update(ref for comparison in self.comparisons
                    for ref in [*comparison.evidence_ids, *comparison.conflicting_evidence_ids])
        if refs - evidence_ids:
            raise ValueError("Every assessment finding and comparison must cite included evidence")
        return self


class PipelineAuthenticityAssessment(BaseModel):
    """Legacy provider-workflow result, superseded by rule-based Sprint 4 assessment."""

    assessment_id: str = Field(default_factory=_new_id)
    check_id: str
    verdict: AuthenticityVerdict
    outcome_evidence_ids: list[str] = Field(min_length=1)
    identity: ProductIdentity
    evidence_sources: list[EvidenceSource]
    evidence: list[Evidence]
    comparisons: list[EvidenceComparison] = Field(default_factory=list)
    claims: list[AssessmentClaim] = Field(default_factory=list)
    assessed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def every_claim_resolves_to_evidence(self) -> PipelineAuthenticityAssessment:
        source_ids = [source.source_id for source in self.evidence_sources]
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Evidence source IDs must be unique")
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("Evidence IDs must be unique")
        if {item.source_id for item in self.evidence} - set(source_ids):
            raise ValueError("Every evidence item must reference an included source")
        if {ref for item in self.evidence for ref in item.derived_from_evidence_ids} - set(evidence_ids):
            raise ValueError("Derived evidence must reference included evidence")

        referenced_ids = set(evidence_ids)
        references = [
            self.outcome_evidence_ids,
            self.identity.evidence_ids,
            *self.identity.field_evidence_ids.values(),
        ]
        references.extend(claim.evidence_ids for claim in self.claims)
        references.extend(comparison.evidence_ids for comparison in self.comparisons)
        if any(set(ids) - referenced_ids for ids in references):
            raise ValueError("Every assessment claim and comparison must cite included evidence")
        if self.verdict != "insufficient_evidence" and not self.claims:
            raise ValueError("An authenticity verdict requires at least one evidence-linked claim")
        return self


class IdentificationResult(BaseModel):
    identity: ProductIdentity
    evidence_bundle: EvidenceBundle


class ImageQualityReport(BaseModel):
    status: Literal["good", "retake_recommended"]
    issues: list[str] = Field(default_factory=list)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    sharpness_score: float = Field(ge=0.0)
    brightness: float = Field(ge=0.0, le=255.0)


class OCRExtraction(BaseModel):
    text: str = ""
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class SubmittedPhoto(BaseModel):
    image_id: str = Field(default_factory=_new_id)
    filename: str
    content_type: Literal["image/jpeg", "image/png", "image/webp"]
    size_bytes: int = Field(gt=0)
    storage_key: str
    quality: ImageQualityReport
    ocr_status: Literal["complete", "unavailable", "failed"]
    ocr_text: str = ""
    ocr_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    provider_message: str | None = None
    vision_status: Literal["complete", "unavailable", "failed"] = "unavailable"
    vision_message: str | None = None
    vision_evidence_ids: list[str] = Field(default_factory=list)


class VerificationSubmission(BaseModel):
    check: AuthenticityCheck
    candidate: ProductIdentity
    photos: list[SubmittedPhoto] = Field(min_length=1)
    evidence_sources: list[EvidenceSource] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    missing_identity_fields: list[str] = Field(default_factory=list)
    conflicting_fields: list[str] = Field(default_factory=list)
    guidance: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def candidate_evidence_is_included(self) -> VerificationSubmission:
        source_ids = {source.source_id for source in self.evidence_sources}
        evidence_ids = {item.evidence_id for item in self.evidence}
        if any(item.source_id not in source_ids for item in self.evidence):
            raise ValueError("Every submission evidence item must reference an included source")
        if {ref for item in self.evidence for ref in item.derived_from_evidence_ids} - evidence_ids:
            raise ValueError("Derived submission evidence must reference included evidence")
        if set(self.candidate.evidence_ids) - evidence_ids:
            raise ValueError("Candidate identity references evidence absent from the submission")
        if {ref for photo in self.photos for ref in photo.vision_evidence_ids} - evidence_ids:
            raise ValueError("Photo vision references evidence absent from the submission")
        field_references = {
            evidence_id
            for ids in self.candidate.field_evidence_ids.values()
            for evidence_id in ids
        }
        if field_references - evidence_ids:
            raise ValueError("Candidate fields reference evidence absent from the submission")
        return self
