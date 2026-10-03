"""Evidence collection and identity matching using Brave's documented JSON API."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
from typing import NotRequired, Protocol, TypedDict
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from .domain import (
    Evidence,
    EvidenceSource,
    IdentityFieldComparison,
    ProductIdentificationReport,
    ProductIdentity,
    ProductIdentityCandidate,
    VerificationSubmission,
)
from .source_trust import classify_source


class SearchConfigurationError(RuntimeError):
    pass


class SearchProviderError(RuntimeError):
    pass


class WebSearchResult(TypedDict):
    """Normalized result directly returned by the configured search service."""

    title: str
    url: str
    description: str
    age: NotRequired[str | None]


class WebSearchClient(Protocol):
    def search(self, query: str, *, count: int, country: str) -> list[WebSearchResult]: ...


class BraveSearchClient:
    provider_name = "brave_search"
    endpoint = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str | None = None, *, timeout: float = 12.0) -> None:
        self.api_key = api_key or os.environ.get("BRAVE_SEARCH_API_KEY")
        self.timeout = timeout
        if not self.api_key:
            raise SearchConfigurationError("BRAVE_SEARCH_API_KEY is required for external product research")

    def search(self, query: str, *, count: int = 10, country: str = "IN") -> list[WebSearchResult]:
        params = urlencode({"q": query, "count": count, "country": country, "search_lang": "en"})
        request = Request(
            f"{self.endpoint}?{params}",
            headers={"Accept": "application/json", "X-Subscription-Token": self.api_key or ""},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise SearchProviderError("External web search request failed") from exc
        web_payload = payload.get("web") if isinstance(payload, dict) else None
        results = web_payload.get("results", []) if isinstance(web_payload, dict) else []
        normalized: list[WebSearchResult] = []
        for result in results:
            if not isinstance(result, dict):
                continue
            url = result.get("url")
            title = result.get("title")
            if not isinstance(url, str) or urlparse(url).scheme not in {"http", "https"}:
                continue
            if not isinstance(title, str) or not title.strip():
                continue
            normalized.append(WebSearchResult(
                title=title.strip(), url=url, description=str(result.get("description") or "").strip(),
                age=str(result.get("age") or "") or None,
            ))
        return normalized


OFFICIAL_DOMAINS = {
    "nike": "nike.com/in", "puma": "in.puma.com", "asics": "asics.co.in",
    "skechers": "skechers.in", "adidas": "adidas.co.in", "crocs": "crocs.in",
    "new balance": "newbalance.co.in",
}
TRUSTED_RETAILER_DOMAINS = {
    "myntra.com", "ajio.com", "amazon.in", "tatacliq.com", "flipkart.com",
}
IDENTITY_FIELDS = ("brand", "product_name", "model_number", "sku", "style_code", "size", "colorway")


def _clean(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


def _official_domain(brand: str | None) -> str | None:
    normalized = (brand or "").casefold()
    return next((domain for key, domain in OFFICIAL_DOMAINS.items() if key in normalized), None)


class ProductResearchProvider:
    """Build queries, normalize real search responses, and compare identity fields."""

    provider_name = "brave_search_product_research"

    def __init__(self, search_client: WebSearchClient, *, results_per_query: int = 8) -> None:
        self.search_client = search_client
        self.results_per_query = results_per_query

    def identify(self, submission: VerificationSubmission) -> ProductIdentificationReport:
        identity = submission.candidate
        terms = [identity.brand, identity.product_name, identity.model_number,
                 identity.sku, identity.style_code, identity.colorway]
        terms = list(dict.fromkeys(_clean(term) for term in terms if _clean(term)))
        queries: list[str] = []
        official = _official_domain(identity.brand)
        if official and len(terms) > 1:
            queries.append(f"site:{official} {' '.join(terms)} footwear")
        brand = _clean(identity.brand)
        model = _clean(identity.product_name or identity.model_number)
        code = _clean(identity.sku or identity.style_code)
        colorway = _clean(identity.colorway)
        if brand and model:
            queries.append(f"{brand} {model} footwear India")
        if brand and code:
            queries.append(f"{brand} {code} shoes India")
        if brand and colorway:
            queries.append(f"{brand} {colorway} footwear India")
        if brand and (model or code):
            retailer_sites = " OR ".join(f"site:{domain}" for domain in sorted(TRUSTED_RETAILER_DOMAINS))
            queries.append(f"({retailer_sites}) {brand} {model or code} footwear India")
        if terms and not queries:
            queries.append(f"{' '.join(terms)} footwear India")
        if not terms:
            # A listing title is submitted material, but never expand to a generic product query.
            title = _clean(submission.check.listing_title)
            if title:
                queries.append(f"{title} footwear India")

        results: list[dict] = []
        for query in queries:
            results.extend(self.search_client.search(query, count=self.results_per_query, country="IN"))

        sources: list[EvidenceSource] = []
        evidence: list[Evidence] = []
        candidates: list[ProductIdentityCandidate] = []
        seen_urls: set[str] = set()
        submitted = {name: _clean(getattr(identity, name)) for name in IDENTITY_FIELDS}
        for result in results:
            url = str(result.get("url", ""))
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            source_type, trust_level = classify_source(url)
            official_match = source_type == "official_brand"
            retrieved_at = datetime.now(timezone.utc)
            source = EvidenceSource(source_type=source_type, trust_level=trust_level,
                                   provider=self.provider_name, uri=url,
                                   retrieved_at=retrieved_at)
            sources.append(source)
            title = str(result.get("title", "")).strip()
            description = str(result.get("description", "")).strip()
            observed = f"Search result title: {title}"
            if description:
                observed += f"\nSearch result description: {description}"
            item = Evidence(source_id=source.source_id, evidence_type="text_observation",
                            subject="external_search_result", observation=observed, captured_at=retrieved_at,
                            source_url=url, retrieved_at=retrieved_at, provider=self.provider_name,
                            supporting_text=observed, confidence=1.0, source_trust_level=trust_level)
            evidence.append(item)
            text = f"{title} {description}".casefold()
            comparisons: list[IdentityFieldComparison] = []
            matched_fields: list[str] = []
            contradicted_fields: list[str] = []
            field_evidence: dict[str, list[str]] = {}
            result_field_evidence: dict[str, Evidence] = {}
            code_label = re.search(
                r"(?P<label>SKU|style\s*(?:code|no\.?|number)?|model\s*(?:no\.?|number))\s*[:#-]?\s*(?P<value>[A-Z0-9][A-Z0-9-]{3,})",
                f"{title} {description}", re.I,
            )
            explicit_code: tuple[str, str] | None = None
            if code_label:
                label = code_label.group("label").casefold()
                code_field = "sku" if label == "sku" else "style_code" if label.startswith("style") else "model_number"
                explicit_code = (code_field, code_label.group("value"))
            for field, value in submitted.items():
                if not value:
                    continue
                if explicit_code and explicit_code[0] == field and explicit_code[1].casefold() != value.casefold():
                    contradicted_fields.append(field)
                    claim = code_label.group(0) if code_label else f"{field}: {explicit_code[1]}"
                    field_item = Evidence(
                        source_id=source.source_id, evidence_type="catalogue_attribute", subject=field,
                        observation=f"Search result explicitly labels {claim}",
                        exact_claim=f"{field}: {explicit_code[1]}",
                        source_url=url, retrieved_at=retrieved_at, provider=self.provider_name,
                        supporting_text=claim, confidence=1.0, source_trust_level=trust_level,
                        derived_from_evidence_ids=[item.evidence_id],
                    )
                    evidence.append(field_item)
                    result_field_evidence[field] = field_item
                    field_evidence[field] = [field_item.evidence_id]
                    comparisons.append(IdentityFieldComparison(
                        field=field, submitted_value=value, researched_value=explicit_code[1],
                        result="contradiction", evidence_ids=[field_item.evidence_id],
                    ))
                elif value.casefold() in text:
                    matched_fields.append(field)
                    match = re.search(re.escape(value), f"{title} {description}", re.I)
                    snippet = match.group(0) if match else value
                    field_item = Evidence(
                        source_id=source.source_id, evidence_type="catalogue_attribute", subject=field,
                        observation=f"Search result contains {field}: {snippet}",
                        exact_claim=f"{field}: {snippet}", source_url=url,
                        retrieved_at=retrieved_at, provider=self.provider_name,
                        supporting_text=snippet, confidence=1.0, source_trust_level=trust_level,
                        derived_from_evidence_ids=[item.evidence_id],
                    )
                    evidence.append(field_item)
                    result_field_evidence[field] = field_item
                    field_evidence[field] = [field_item.evidence_id]
                    comparisons.append(IdentityFieldComparison(
                        field=field, submitted_value=value, researched_value=snippet,
                        result="match", evidence_ids=[field_item.evidence_id],
                    ))
                else:
                    comparisons.append(IdentityFieldComparison(
                        field=field, submitted_value=value, result="not_observed",
                    ))

            if not matched_fields and not contradicted_fields:
                continue
            confidence = min(0.95, 0.35 + 0.15 * len(matched_fields) + 0.2 * int(official_match))
            candidate_identity = ProductIdentity(
                brand=identity.brand if "brand" in matched_fields else None,
                product_name=title or None,
                model_number=identity.model_number if "model_number" in matched_fields else None,
                sku=identity.sku if "sku" in matched_fields else None,
                style_code=identity.style_code if "style_code" in matched_fields else None,
                size=identity.size if "size" in matched_fields else None,
                colorway=identity.colorway if "colorway" in matched_fields else None,
                confidence=confidence,
                field_confidence={field: confidence for field in matched_fields},
                evidence_ids=[item.evidence_id, *[e.evidence_id for e in result_field_evidence.values()]],
                field_evidence_ids=field_evidence,
            )
            candidates.append(ProductIdentityCandidate(identity=candidate_identity, confidence=confidence,
                                                        comparisons=comparisons,
                                                        evidence_ids=[item.evidence_id, *[e.evidence_id for e in result_field_evidence.values()]]))

        return ProductIdentificationReport(check_id=submission.check.check_id, provider=self.provider_name,
                                           queries=queries, candidates=candidates,
                                           evidence_sources=sources, evidence=evidence)
