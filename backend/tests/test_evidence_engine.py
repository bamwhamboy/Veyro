from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.domain import (
    AuthenticityCheck,
    Evidence,
    EvidenceComparison,
    EvidenceReport,
    EvidenceSource,
    ImageQualityReport,
    ProductIdentificationReport,
    ProductIdentity,
    SubmittedPhoto,
    VerificationSubmission,
)
from app.evidence_engine import build_evidence_report
from app.source_trust import classify_source
from app.submissions import SQLiteSubmissionRepository


def make_submission(**values: str) -> VerificationSubmission:
    source = EvidenceSource(
        source_id="uploaded-ocr", source_type="ocr_output", provider="mock_ocr",
        uri="upload://photo-1", trust_level="unrated",
    )
    evidence = []
    refs = {}
    for field, value in values.items():
        item = Evidence(
            evidence_id=f"submitted-{field}", source_id=source.source_id,
            evidence_type="text_observation", subject=field,
            observation=f"OCR read {field}: {value}", exact_claim=f"{field}: {value}",
            supporting_text=f"{field.upper()}: {value}", confidence=0.9,
        )
        evidence.append(item)
        refs[field] = [item.evidence_id]
    identity = ProductIdentity(
        **values, confidence=0.9, field_confidence={key: 0.9 for key in values},
        evidence_ids=[item.evidence_id for item in evidence], field_evidence_ids=refs,
    )
    return VerificationSubmission(
        check=AuthenticityCheck(
            check_id="check-evidence-1", listing_title="User-submitted footwear",
            image_urls=["upload://photo-1"],
        ),
        candidate=identity,
        photos=[SubmittedPhoto(
            filename="photo.jpg", content_type="image/jpeg", size_bytes=10,
            storage_key="photo.jpg",
            quality=ImageQualityReport(
                status="good", width=100, height=100, sharpness_score=1, brightness=120,
            ),
            ocr_status="complete",
        )],
        evidence_sources=[source], evidence=evidence,
    )


def research_report(claims: list[tuple[str, str, str]], *, check_id: str = "check-evidence-1") -> ProductIdentificationReport:
    sources = []
    evidence = []
    for index, (field, value, url) in enumerate(claims):
        trust_type, trust = classify_source(url)
        source = EvidenceSource(
            source_id=f"external-source-{index}", source_type=trust_type,
            trust_level=trust, provider="mock_web_search", uri=url,
        )
        sources.append(source)
        evidence.append(Evidence(
            evidence_id=f"external-{index}", source_id=source.source_id,
            evidence_type="catalogue_attribute", subject=field,
            observation=f"Source snippet reports {field}: {value}",
            exact_claim=f"{field}: {value}", source_url=url,
            retrieved_at=source.retrieved_at, provider=source.provider,
            supporting_text=f"{field}: {value}", confidence=0.95,
            source_trust_level=source.trust_level,
        ))
    return ProductIdentificationReport(
        check_id=check_id, provider="mock_research", queries=["mock query"],
        evidence_sources=sources, evidence=evidence,
    )


@pytest.mark.parametrize(
    ("url", "source_type", "trust"),
    [
        ("https://www.nike.com/in/t/shoe", "official_brand", "very_high"),
        ("https://retailer.example.in/item", "authorised_retailer", "high"),
        ("https://www.myntra.com/item", "established_marketplace", "medium"),
        ("https://unknown.example/item", "other_web", "low"),
    ],
)
def test_source_trust_classification(url, source_type, trust, monkeypatch) -> None:
    if source_type == "authorised_retailer":
        monkeypatch.setenv("VEYRO_AUTHORISED_RETAILER_DOMAINS", "retailer.example.in")
    assert classify_source(url) == (source_type, trust)


def test_domain_matching_does_not_accept_lookalike_hosts() -> None:
    assert classify_source("https://nike.com.attacker.example/item") == ("other_web", "low")


def test_official_match_wins_over_conflicting_marketplace_evidence() -> None:
    submission = make_submission(sku="ABCD1234")
    report = build_evidence_report(submission, research_report([
        ("sku", "ABCD1234", "https://nike.com/in/shoe"),
        ("sku", "WRONG999", "https://www.myntra.com/shoe"),
    ]))

    comparison = next(item for item in report.comparisons if item.dimension == "sku")
    assert comparison.result == "match"
    assert comparison.source_trust_level == "very_high"
    assert comparison.conflicting_evidence_ids == ["external-1"]
    assert "Lower-trust" in comparison.explanation


def test_strong_official_contradiction_is_not_overridden_by_marketplace_match() -> None:
    submission = make_submission(style_code="SUBMITTED123")
    report = build_evidence_report(submission, research_report([
        ("style_code", "OTHER123", "https://www.adidas.co.in/shoe"),
        ("style_code", "SUBMITTED123", "https://www.myntra.com/shoe"),
    ]))
    comparison = next(item for item in report.comparisons if item.dimension == "style_code")
    assert comparison.result == "mismatch"
    assert comparison.evidence_status == "contradicted"
    assert comparison.external_value == "OTHER123"
    assert comparison.conflicting_evidence_ids == ["external-1"]


def test_conflicting_sources_at_same_trust_level_are_insufficient_evidence() -> None:
    report = build_evidence_report(make_submission(sku="ABC123"), research_report([
        ("sku", "ABC123", "https://www.nike.com/item-a"),
        ("sku", "XYZ789", "https://www.adidas.com/item-b"),
    ]))
    comparison = next(item for item in report.comparisons if item.dimension == "sku")
    assert comparison.result == "insufficient_evidence"
    assert comparison.evidence_status == "insufficient_evidence"
    assert len(comparison.evidence_ids) == 3


def test_low_trust_claims_cannot_produce_match_or_mismatch() -> None:
    report = build_evidence_report(make_submission(sku="ABC123"), research_report([
        ("sku", "WRONG999", "https://unknown.example/item"),
    ]))
    comparison = next(item for item in report.comparisons if item.dimension == "sku")
    assert comparison.result == "insufficient_evidence"
    assert comparison.evidence_status == "insufficient_evidence"


def test_no_external_attribute_is_not_found_and_never_a_mismatch() -> None:
    report = build_evidence_report(make_submission(sku="ABC123"), research_report([
        ("colorway", "Black", "https://www.nike.com/item"),
    ]))
    comparison = next(item for item in report.comparisons if item.dimension == "sku")
    assert comparison.result == "unknown"
    assert comparison.evidence_status == "not_found"
    assert comparison.evidence_ids == ["submitted-sku"]


def test_no_research_and_no_submitted_observation_are_not_yet_checked() -> None:
    report = build_evidence_report(make_submission(sku="ABC123"), None)
    sku = next(item for item in report.comparisons if item.dimension == "sku")
    size = next(item for item in report.comparisons if item.dimension == "size")
    assert report.status == "not_yet_checked"
    assert sku.evidence_status == "not_yet_checked"
    assert size.evidence_status == "not_yet_checked"
    assert sku.result == size.result == "unknown"


def test_normalizes_material_size_packaging_and_retains_trace_metadata() -> None:
    source = EvidenceSource(
        source_id="search-source", source_type="official_brand", trust_level="high",
        provider="search", uri="https://www.asics.com/item",
    )
    raw = Evidence(
        evidence_id="snippet", source_id=source.source_id, evidence_type="text_observation",
        subject="external_search_result",
        observation="Search result title: Model GT-2000\nSearch result description: Size: US 9. Materials: mesh upper. Packaging: branded shoe box.",
    )
    report = ProductIdentificationReport(
        check_id="check-evidence-1", provider="search", evidence_sources=[source], evidence=[raw],
    )
    evidence_report = build_evidence_report(make_submission(), report)

    normalized = {item.subject: item for item in evidence_report.evidence if item.exact_claim}
    assert {"product_name", "size", "materials", "packaging"} <= normalized.keys()
    for field in ("product_name", "size", "materials", "packaging"):
        item = normalized[field]
        assert item.source_url == source.uri
        assert item.retrieved_at is not None
        assert item.provider == "search"
        assert item.supporting_text
        assert item.confidence is not None
        assert item.source_trust_level == "very_high"


def test_uploaded_ocr_material_observation_compares_to_external_claim() -> None:
    submission = make_submission()
    source = submission.evidence_sources[0]
    raw_ocr = Evidence(
        evidence_id="uploaded-raw-ocr", source_id=source.source_id,
        evidence_type="text_observation", subject="ocr_text",
        observation="OCR extracted text: Materials: leather and mesh.",
        supporting_text="Materials: leather and mesh.", confidence=0.88,
    )
    submission = submission.model_copy(update={"evidence": [raw_ocr]})
    report = build_evidence_report(submission, research_report([
        ("materials", "leather and mesh", "https://www.nike.com/in/shoe"),
    ]))

    comparison = next(item for item in report.comparisons if item.dimension == "materials")
    assert comparison.result == "match"
    assert comparison.submitted_value == comparison.external_value == "leather and mesh"
    assert "uploaded-raw-ocr" in comparison.evidence_ids
    assert "external-0" in comparison.evidence_ids


def test_evidence_report_rejects_dangling_comparison_evidence() -> None:
    with pytest.raises(ValidationError, match="reference must resolve"):
        EvidenceReport(
            check_id="check-1", status="complete",
            comparisons=[{
                "dimension": "sku", "result": "mismatch", "explanation": "different",
                "evidence_ids": ["missing"],
            }],
        )


def test_absence_of_evidence_cannot_be_encoded_as_a_mismatch() -> None:
    with pytest.raises(ValidationError, match="must remain unknown"):
        EvidenceComparison(
            dimension="sku", result="mismatch", evidence_status="not_found",
            explanation="No source value was found.",
        )


def test_complete_evidence_report_round_trips_through_sqlite(tmp_path) -> None:
    report = build_evidence_report(
        make_submission(sku="ABC123"),
        research_report([("sku", "ABC123", "https://www.nike.com/item")]),
    )
    repository = SQLiteSubmissionRepository(tmp_path / "evidence.sqlite3")

    repository.save_evidence_report(report)
    restored = repository.get_evidence_report(report.check_id)

    assert restored == report
    comparison = next(item for item in restored.comparisons if item.dimension == "sku")
    assert {"submitted-sku", "external-0"} <= set(comparison.evidence_ids)
