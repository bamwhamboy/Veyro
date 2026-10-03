import pytest
from pydantic import ValidationError

from app.domain import (
    AssessmentClaim,
    PipelineAuthenticityAssessment,
    AuthenticityCheck,
    Evidence,
    EvidenceBundle,
    EvidenceSource,
    ProductIdentity,
)


def evidence_pair() -> tuple[EvidenceSource, Evidence]:
    source = EvidenceSource(
        source_id="source-1",
        source_type="user_listing",
        provider="user_submission",
        uri="https://shop.example.in/item",
    )
    item = Evidence(
        evidence_id="evidence-1",
        source_id=source.source_id,
        evidence_type="listing_field",
        subject="listed_model_number",
        observation="The listing states model ABC-123.",
    )
    return source, item


def test_authenticity_check_requires_footwear_submission_material() -> None:
    with pytest.raises(ValidationError):
        AuthenticityCheck()
    check = AuthenticityCheck(image_urls=["https://uploads.example.in/photo.jpg"])
    assert check.market == "IN"
    assert check.category == "footwear"


def test_assessment_requires_claim_and_outcome_evidence_to_resolve() -> None:
    source, item = evidence_pair()
    assessment = PipelineAuthenticityAssessment(
        check_id="check-1",
        verdict="inconclusive",
        outcome_evidence_ids=[item.evidence_id],
        identity=ProductIdentity(
            model_number="ABC-123", evidence_ids=[item.evidence_id]
        ),
        evidence_sources=[source],
        evidence=[item],
        claims=[
            AssessmentClaim(
                statement="The listing provides a model number for comparison.",
                direction="neutral",
                evidence_ids=[item.evidence_id],
            )
        ],
    )
    assert assessment.claims[0].evidence_ids == ["evidence-1"]

    with pytest.raises(ValidationError, match="cite included evidence"):
        PipelineAuthenticityAssessment(
            check_id="check-1",
            verdict="likely_authentic",
            outcome_evidence_ids=["missing"],
            identity=ProductIdentity(),
            evidence_sources=[source],
            evidence=[item],
            claims=[
                AssessmentClaim(
                    statement="Unsupported claim",
                    direction="supports_authenticity",
                    evidence_ids=[item.evidence_id],
                )
            ],
        )


def test_assessment_claim_cannot_be_created_without_evidence_references() -> None:
    with pytest.raises(ValidationError):
        AssessmentClaim(
            statement="Untraceable assertion",
            direction="raises_concern",
            evidence_ids=[],
        )


def test_evidence_must_reference_a_known_source() -> None:
    with pytest.raises(ValidationError, match="unknown sources"):
        EvidenceBundle(
            evidence=[
                Evidence(
                    evidence_id="orphan",
                    source_id="missing",
                    evidence_type="visual_observation",
                    subject="stitching",
                    observation="Visible stitching pattern.",
                )
            ]
        )
