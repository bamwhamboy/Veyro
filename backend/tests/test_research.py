from datetime import datetime, timezone

import pytest

from app.domain import (
    AuthenticityCheck,
    ImageQualityReport,
    ProductIdentity,
    SubmittedPhoto,
    VerificationSubmission,
)
from app.research import (
    BraveSearchClient,
    ProductResearchProvider,
    SearchConfigurationError,
    WebSearchResult,
)
from app.submissions import SQLiteSubmissionRepository


def submission(**identity_fields: str) -> VerificationSubmission:
    now = datetime.now(timezone.utc)
    return VerificationSubmission(
        check=AuthenticityCheck(listing_title="Footwear label submission", image_urls=["upload://photo"]),
        candidate=ProductIdentity(**identity_fields, confidence=0.8),
        photos=[SubmittedPhoto(
            filename="label.jpg", content_type="image/jpeg", size_bytes=1, storage_key="x.jpg",
            quality=ImageQualityReport(status="good", width=100, height=100, sharpness_score=1, brightness=120),
            ocr_status="complete",
        )],
    )


class MockSearch:
    def __init__(self, results: list[WebSearchResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, int, str]] = []

    def search(self, query: str, *, count: int, country: str) -> list[WebSearchResult]:
        self.calls.append((query, count, country))
        return self.results


def test_brave_search_requires_environment_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    with pytest.raises(SearchConfigurationError):
        BraveSearchClient()


def test_brave_client_parses_json_and_rejects_non_web_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.research as research

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return b'{"web":{"results":[{"title":"Shoe","url":"https://nike.com/in/shoe","description":"SKU: ABCD1234"},{"title":"bad","url":"javascript:alert(1)"}]}}'

    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["key"] = request.get_header("X-subscription-token")
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(research, "urlopen", fake_urlopen)
    client = BraveSearchClient("secret", timeout=3)
    results = client.search("Nike shoe", count=4, country="IN")
    assert len(results) == 1
    assert results[0]["title"] == "Shoe"
    assert "country=IN" in captured["url"]
    assert captured["key"] == "secret"
    assert captured["timeout"] == 3


def test_research_prioritizes_official_query_and_links_matches_to_real_result_evidence() -> None:
    search = MockSearch([WebSearchResult(
        title="Nike Air Zoom Pegasus 41 Black/White",
        url="https://www.nike.com/in/t/air-zoom-pegasus-41-shoes-X123",
        description="Nike running shoes. Style Code: ABCD1234-001",
    )])
    submission_data = submission(brand="Nike", product_name="Air Zoom Pegasus 41", style_code="ABCD1234-001", colorway="Black/White")

    report = ProductResearchProvider(search).identify(submission_data)

    assert search.calls[0][0].startswith("site:nike.com/in")
    assert all(call[2] == "IN" for call in search.calls)
    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.identity.product_name == "Nike Air Zoom Pegasus 41 Black/White"
    assert candidate.identity.evidence_ids == candidate.evidence_ids
    assert candidate.confidence > 0
    assert any(item.result == "match" and item.field == "style_code" for item in candidate.comparisons)
    assert report.evidence_sources[0].source_type == "official_brand"
    assert report.evidence_sources[0].trust_level == "very_high"
    assert report.evidence_sources[0].uri == "https://www.nike.com/in/t/air-zoom-pegasus-41-shoes-X123"
    assert report.evidence_sources[0].retrieved_at.tzinfo is not None
    assert report.evidence[0].source_id == report.evidence_sources[0].source_id
    assert report.evidence[0].captured_at == report.evidence_sources[0].retrieved_at


def test_research_records_explicit_code_contradictions_and_leaves_unobserved_fields_unknown() -> None:
    search = MockSearch([WebSearchResult(
        title="Adidas Ultraboost 5",
        url="https://www.adidas.co.in/ultraboost",
        description="Style Code: DIFFERENT123",
    )])
    report = ProductResearchProvider(search).identify(submission(
        brand="Adidas", product_name="Ultraboost", style_code="SUBMITTED123", colorway="Core Black",
    ))

    comparisons = report.candidates[0].comparisons
    assert any(item.field == "style_code" and item.result == "contradiction" and item.evidence_ids for item in comparisons)
    assert any(item.field == "colorway" and item.result == "not_observed" and not item.evidence_ids for item in comparisons)


def test_research_does_not_create_candidates_without_supported_matches() -> None:
    search = MockSearch([WebSearchResult(
        title="Running shoes", url="https://example.org/shoes", description="General footwear listing",
    )])
    report = ProductResearchProvider(search).identify(submission(brand="Puma", sku="KNOWN123"))
    assert report.candidates == []
    assert report.evidence  # the external response itself remains recorded as evidence


def test_research_report_and_source_metadata_are_persisted(tmp_path) -> None:
    search = MockSearch([WebSearchResult(
        title="Puma Deviate Nitro 3", url="https://in.puma.com/deviate-nitro-3",
        description="Running footwear",
    )])
    report = ProductResearchProvider(search).identify(submission(brand="Puma", product_name="Deviate Nitro 3"))
    repository = SQLiteSubmissionRepository(tmp_path / "veyro.sqlite3")

    repository.save_research_report(report)
    restored = repository.get_research_report(report.check_id)

    assert restored == report
    assert restored.evidence_sources[0].uri == "https://in.puma.com/deviate-nitro-3"
    assert restored.evidence_sources[0].retrieved_at == restored.evidence[0].captured_at
