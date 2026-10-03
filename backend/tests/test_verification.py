from app.domain import (
    AssessmentClaim,
    AssessmentDecision,
    AuthenticityCheck,
    Evidence,
    EvidenceBundle,
    EvidenceComparison,
    EvidenceSource,
    IdentificationResult,
    ProductIdentity,
)
from app.verification import run_authenticity_check


def test_workflow_runs_in_order_and_returns_evidence_linked_assessment() -> None:
    steps: list[str] = []
    listing_source = EvidenceSource(
        source_id="listing-source",
        source_type="user_listing",
        provider="test_identifier",
        uri="https://retailer.example.in/listing",
    )
    listing_evidence = Evidence(
        evidence_id="listing-model",
        source_id=listing_source.source_id,
        evidence_type="listing_field",
        subject="model_number",
        observation="Listing states model ABC-123.",
    )
    identity = ProductIdentity(
        brand="Example Brand",
        model_number="ABC-123",
        evidence_ids=[listing_evidence.evidence_id],
    )

    class Identifier:
        def identify(self, check):
            steps.append("identify")
            assert check.listing_url == listing_source.uri
            return IdentificationResult(
                identity=identity,
                evidence_bundle=EvidenceBundle(
                    sources=[listing_source], evidence=[listing_evidence]
                ),
            )

    class OCR:
        provider_kind = "ocr"

        def collect(self, check, candidate):
            steps.append("collect")
            assert candidate.model_number == "ABC-123"
            source = EvidenceSource(
                source_id="ocr-source",
                source_type="ocr_output",
                provider="test_ocr",
            )
            evidence = Evidence(
                evidence_id="label-model",
                source_id=source.source_id,
                evidence_type="text_observation",
                subject="shoe_label_model",
                observation="The photographed label reads ABC-123.",
            )
            return EvidenceBundle(sources=[source], evidence=[evidence])

    class Comparer:
        def compare(self, candidate, evidence):
            steps.append("compare")
            return [EvidenceComparison(
                dimension="model_number",
                result="match",
                explanation="Listing and photographed label show the same model number.",
                evidence_ids=[item.evidence_id for item in evidence],
            )]

    class Assessor:
        def assess(self, candidate, evidence, comparisons):
            steps.append("assess")
            return AssessmentDecision(
                verdict="inconclusive",
                outcome_evidence_ids=[item.evidence_id for item in evidence],
                claims=[
                    AssessmentClaim(
                        statement="The listed and photographed model numbers match.",
                        direction="supports_authenticity",
                        evidence_ids=[item.evidence_id for item in evidence],
                    )
                ],
            )

    assessment = run_authenticity_check(
        AuthenticityCheck(listing_url=listing_source.uri),
        identifier=Identifier(),
        evidence_providers=[OCR()],
        comparer=Comparer(),
        assessor=Assessor(),
    )

    assert steps == ["identify", "collect", "compare", "assess"]
    assert assessment.identity.model_number == "ABC-123"
    assert len(assessment.evidence) == 2
    assert set(assessment.claims[0].evidence_ids) == {
        "listing-model", "label-model"
    }


def test_workflow_rejects_provider_decisions_with_dangling_evidence() -> None:
    source = EvidenceSource(
        source_id="source", source_type="user_listing", provider="test"
    )
    item = Evidence(
        evidence_id="evidence",
        source_id=source.source_id,
        evidence_type="listing_field",
        subject="model",
        observation="Model ABC-123.",
    )

    class Identifier:
        def identify(self, check):
            return IdentificationResult(
                identity=ProductIdentity(),
                evidence_bundle=EvidenceBundle(sources=[source], evidence=[item]),
            )

    class Comparer:
        def compare(self, identity, evidence):
            return []

    class Assessor:
        def assess(self, identity, evidence, comparisons):
            return AssessmentDecision(
                verdict="likely_authentic", outcome_evidence_ids=["fabricated-id"],
                claims=[
                    AssessmentClaim(
                        statement="Looks authentic.",
                        direction="supports_authenticity",
                        evidence_ids=[item.evidence_id],
                    )
                ],
            )

    try:
        run_authenticity_check(
            AuthenticityCheck(listing_title="Footwear listing"),
            identifier=Identifier(),
            evidence_providers=[],
            comparer=Comparer(),
            assessor=Assessor(),
        )
    except ValueError as error:
        assert "cite included evidence" in str(error)
    else:
        raise AssertionError("workflow accepted an unsupported verdict reference")
