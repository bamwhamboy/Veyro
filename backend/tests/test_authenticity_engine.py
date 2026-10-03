import pytest
from pydantic import ValidationError

from app.authenticity_engine import build_authenticity_assessment
from app.domain import AuthenticityAssessment
from app.evidence_engine import build_evidence_report
from app.submissions import SQLiteSubmissionRepository
from tests.test_evidence_engine import make_submission, research_report


def evaluate(submission, research=None):
    evidence_report = build_evidence_report(submission, research)
    return build_authenticity_assessment(submission, evidence_report)


def test_strong_consistent_identity_signals_support_likely_authentic() -> None:
    submission = make_submission(
        brand="Nike", product_name="Air Zoom Pegasus 41", sku="ABCD1234",
    )
    assessment = evaluate(submission, research_report([
        ("brand", "Nike", "https://www.nike.com/in/pegasus-41"),
        ("product_name", "Air Zoom Pegasus 41", "https://www.nike.com/in/pegasus-41"),
        ("sku", "ABCD1234", "https://www.nike.com/in/pegasus-41"),
    ]))

    assert assessment.overall_assessment == "likely_authentic"
    assert assessment.confidence in {"moderate", "high"}
    assert all(item.classification == "supporting" for item in assessment.supporting_findings)
    assert assessment.evidence_ids
    assert "not a probability" in assessment.confidence_basis


def test_authoritative_identifier_contradiction_supports_likely_counterfeit() -> None:
    submission = make_submission(sku="SUBMITTED123")
    assessment = evaluate(submission, research_report([
        ("sku", "OFFICIAL999", "https://www.nike.com/in/product"),
        ("sku", "SUBMITTED123", "https://www.myntra.com/product"),
    ]))

    assert assessment.overall_assessment == "likely_counterfeit"
    assert assessment.contradictions
    assert assessment.contradictions[0].dimension == "sku"
    assert assessment.contradictions[0].source_trust_level == "very_high"


def test_insufficient_evidence_is_inconclusive_not_counterfeit() -> None:
    assessment = evaluate(make_submission(sku="ABC123"))

    assert assessment.overall_assessment == "inconclusive"
    assert assessment.missing_evidence
    assert all(item.classification in {"unknown", "insufficient_evidence"} for item in assessment.missing_evidence)
    assert not assessment.contradictions


def test_conflicting_authoritative_sources_force_inconclusive() -> None:
    submission = make_submission(sku="ABC123")
    assessment = evaluate(submission, research_report([
        ("sku", "ABC123", "https://www.nike.com/product-a"),
        ("sku", "DIFFERENT999", "https://www.adidas.com/product-b"),
    ]))

    assert assessment.overall_assessment == "inconclusive"
    assert any(item.dimension == "sku" and item.classification == "insufficient_evidence"
               for item in assessment.missing_evidence)


def test_missing_identity_fields_are_unknown_and_cited() -> None:
    assessment = evaluate(make_submission())

    missing_dimensions = {item.dimension for item in assessment.missing_evidence}
    assert {"brand", "product_name", "sku", "uploaded_image_observations"} <= missing_dimensions
    assert all(item.evidence_ids for item in assessment.missing_evidence)
    assert assessment.overall_assessment == "inconclusive"


def test_listing_seller_and_uploaded_photo_are_unknown_until_independently_checked() -> None:
    submission = make_submission(sku="ABC123")
    submission = submission.model_copy(update={
        "check": submission.check.model_copy(update={
            "seller_name": "Seller name from user", "listing_url": "https://shop.example.in/item",
        })
    })
    assessment = evaluate(submission)

    unknown_dimensions = {item.dimension for item in assessment.missing_evidence}
    assert {"seller_name", "listing_url", "uploaded_image_observations"} <= unknown_dimensions
    assert any("not been independently verified" in item.statement for item in assessment.missing_evidence)


def test_high_trust_contradiction_outweighs_a_weak_matching_signal() -> None:
    submission = make_submission(style_code="SUBMITTED123")
    assessment = evaluate(submission, research_report([
        ("style_code", "OFFICIAL999", "https://www.asics.com/product"),
        ("style_code", "SUBMITTED123", "https://unknown.example/listing"),
    ]))
    comparison = next(item for item in assessment.comparisons if item.dimension == "style_code")

    assert comparison.result == "mismatch"
    assert comparison.conflicting_evidence_ids
    assert assessment.overall_assessment == "likely_counterfeit"


def test_assessment_validator_rejects_findings_without_resolving_evidence() -> None:
    with pytest.raises(ValidationError, match="cite included evidence"):
        AuthenticityAssessment(
            check_id="check-x", overall_assessment="inconclusive", confidence="low",
            confidence_basis="Qualitative only.", summary="Evidence is incomplete.",
            supporting_findings=[{
                "dimension": "sku", "classification": "supporting",
                "statement": "The code matches.", "evidence_ids": ["absent"],
            }],
        )


def test_assessment_round_trips_through_sqlite_with_complete_evidence_trail(tmp_path) -> None:
    submission = make_submission(sku="ABC123")
    assessment = evaluate(submission, research_report([
        ("sku", "ABC123", "https://www.nike.com/product"),
    ]))
    repository = SQLiteSubmissionRepository(tmp_path / "assessment.sqlite3")

    repository.save_assessment(assessment)
    restored = repository.get_assessment(assessment.check_id)

    assert restored == assessment
    assert restored.evidence_ids
    assert restored.evidence_sources
    assert restored.evidence
    assert restored.comparisons
