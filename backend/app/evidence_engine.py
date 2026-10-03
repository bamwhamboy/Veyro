"""Normalize submission/search observations and compare them without verdicts."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import re

from .domain import (
    Evidence,
    EvidenceComparison,
    EvidenceReport,
    EvidenceSource,
    ProductIdentificationReport,
    VerificationSubmission,
)
from .source_trust import classify_source

TRUST_RANK = {"unrated": 0, "low": 1, "medium": 2, "high": 3, "very_high": 4}
COMPARE_FIELDS = (
    "brand", "product_name", "model_number", "sku", "style_code", "size",
    "colorway", "materials", "specifications", "packaging", "label_info",
    "serial", "ean", "upc", "barcode",
)
ATTRIBUTE_PATTERNS = {
    "sku": re.compile(r"\bSKU\s*[:#-]\s*[A-Z0-9][A-Z0-9./-]{2,}", re.I),
    "style_code": re.compile(r"\b(?:style\s*code|article\s*(?:no\.?|number))\s*[:#-]\s*[A-Z0-9][A-Z0-9./-]{2,}", re.I),
    "model_number": re.compile(r"\bmodel\s*(?:no\.?|number|#)\s*[:#-]?\s*[A-Z0-9][A-Z0-9./-]{2,}", re.I),
    "size": re.compile(r"\b(?:size\s*[:#-]?\s*(?:(?:US|UK|EU|EUR|CM)\s*)?[0-9]{1,2}(?:\.[05])?|(?:US|UK|EU|EUR|CM)\s*size\s*[0-9]{1,2}(?:\.[05])?)\b", re.I),
    "colorway": re.compile(r"\bcolou?r\s*[:#-]\s*[A-Za-z][A-Za-z /-]{1,40}", re.I),
    "materials": re.compile(r"\b(?:materials?|upper|outsole|midsole|lining)\s*[:#-]\s*[^.;,]{2,80}", re.I),
    "specifications": re.compile(r"\b(?:specifications?|features?)\s*[:#-]\s*[^.;]{2,100}", re.I),
    "packaging": re.compile(r"\b(?:packaging|box|shoebox)\s*[:#-]\s*[^.;]{2,80}", re.I),
    "label_info": re.compile(r"\b(?:label|tongue label|size label)\s*[:#-]\s*[^.;]{2,80}", re.I),
    "serial": re.compile(r"\bserial(?:\s*(?:no\.?|number))?\s*[:#-]\s*[A-Z0-9-]{4,}", re.I),
    "ean": re.compile(r"\bEAN\s*[:#-]\s*[0-9]{8,14}", re.I),
    "upc": re.compile(r"\bUPC\s*[:#-]\s*[0-9]{8,14}", re.I),
    "barcode": re.compile(r"\bbarcode\s*[:#-]\s*[0-9A-Z-]{6,}", re.I),
}


def _copy_with_source_metadata(item: Evidence, source: EvidenceSource, *, confidence: float | None = None) -> Evidence:
    return item.model_copy(update={
        "exact_claim": item.exact_claim or item.observation,
        "source_url": source.uri,
        "retrieved_at": source.retrieved_at,
        "provider": source.provider,
        "source_trust_level": source.trust_level,
        "confidence": item.confidence if item.confidence is not None else confidence,
        "supporting_text": item.supporting_text or item.observation,
    })


def _normalized_value(field: str, text: str) -> str:
    labels = {
        "sku": r"SKU", "style_code": r"style\s*code|article\s*(?:no\.?|number)",
        "model_number": r"model\s*(?:no\.?|number|#)", "size": r"size",
        "colorway": r"colou?r", "materials": r"materials?|upper|outsole|midsole|lining",
        "specifications": r"specifications?|features?", "packaging": r"packaging|box|shoebox",
        "label_info": r"label|tongue label|size label", "serial": r"serial(?:\s*(?:no\.?|number))?",
        "ean": r"EAN", "upc": r"UPC", "barcode": r"barcode",
    }.get(field)
    return re.sub(rf"^(?:{labels})\s*[:#-]\s*", "", text, flags=re.I).strip() if labels else text.strip()


def normalize_search_report(report: ProductIdentificationReport) -> tuple[list[EvidenceSource], list[Evidence]]:
    sources: list[EvidenceSource] = []
    for source in report.evidence_sources:
        source_type, trust_level = classify_source(source.uri)
        sources.append(source.model_copy(update={
            "source_type": source_type if source.uri else source.source_type,
            "trust_level": trust_level if source.uri else source.trust_level,
        }))
    source_by_id = {source.source_id: source for source in sources}
    normalized = [
        _copy_with_source_metadata(item, source_by_id[item.source_id], confidence=1.0)
        for item in report.evidence
    ]
    existing = {(item.source_id, item.subject) for item in normalized}
    for item in list(normalized):
        source = source_by_id[item.source_id]
        if item.subject != "external_search_result":
            continue
        text = item.supporting_text or item.observation
        title_match = re.search(r"(?:^|\n)Search result title:\s*(.+?)(?:\n|$)", text)
        if title_match and (source.source_id, "product_name") not in existing:
            title = title_match.group(1).strip()
            if title:
                normalized.append(Evidence(
                    source_id=source.source_id, evidence_type="catalogue_attribute",
                    subject="product_name", observation=f"Search result title: {title}",
                    exact_claim=f"product_name: {title}", source_url=source.uri,
                    retrieved_at=source.retrieved_at, provider=source.provider,
                    supporting_text=title, confidence=0.8, source_trust_level=source.trust_level,
                    derived_from_evidence_ids=[item.evidence_id],
                ))
                existing.add((source.source_id, "product_name"))
        for field, pattern in ATTRIBUTE_PATTERNS.items():
            if (source.source_id, field) in existing:
                continue
            match = pattern.search(text)
            if not match:
                continue
            claim = match.group(0)
            normalized.append(Evidence(
                source_id=source.source_id, evidence_type="catalogue_attribute", subject=field,
                observation=f"Search result text explicitly contains {claim}",
                exact_claim=f"{field}: {_normalized_value(field, claim)}",
                source_url=source.uri, retrieved_at=source.retrieved_at, provider=source.provider,
                supporting_text=claim, confidence=1.0, source_trust_level=source.trust_level,
                derived_from_evidence_ids=[item.evidence_id],
            ))
            existing.add((source.source_id, field))
    return sources, normalized


def build_evidence_report(
    submission: VerificationSubmission,
    research_report: ProductIdentificationReport | None,
) -> EvidenceReport:
    submission_sources = [source.model_copy(update={
        "trust_level": "unrated",
    }) for source in submission.evidence_sources]
    additional_sources: list[EvidenceSource] = []
    additional_evidence: list[Evidence] = []
    listing_values = {
        "listing_title": submission.check.listing_title,
        "seller_name": submission.check.seller_name,
        "listing_url": submission.check.listing_url,
    }
    if any(listing_values.values()):
        listing_source = EvidenceSource(
            source_type="user_listing", trust_level="unrated", provider="user_submission",
            uri=submission.check.listing_url or f"submission://{submission.check.check_id}/listing",
            retrieved_at=submission.check.submitted_at,
        )
        additional_sources.append(listing_source)
        for field, value in listing_values.items():
            if not value:
                continue
            additional_evidence.append(Evidence(
                source_id=listing_source.source_id, evidence_type="listing_field", subject=field,
                observation=f"User submitted {field}: {value}", exact_claim=f"{field}: {value}",
                source_url=listing_source.uri, retrieved_at=listing_source.retrieved_at,
                provider=listing_source.provider, supporting_text=str(value),
                source_trust_level="unrated",
            ))
    image_evidence_ids: list[str] = []
    quality_evidence_ids: list[str] = []
    for photo in submission.photos:
        image_source = EvidenceSource(
            source_type="user_image", trust_level="unrated", provider="user_submission",
            uri=f"upload://{photo.image_id}",
        )
        additional_sources.append(image_source)
        uploaded = Evidence(
            source_id=image_source.source_id, evidence_type="visual_observation",
            subject="uploaded_image", observation=(
                "A footwear photo was submitted and analyzed by the configured vision provider."
                if photo.vision_status == "complete" else
                "A footwear photo was submitted; image contents have not been analyzed by a vision provider."
            ),
            exact_claim="uploaded_image: submitted for review", source_url=image_source.uri,
            retrieved_at=image_source.retrieved_at, provider=image_source.provider,
            supporting_text=photo.filename, source_trust_level="unrated",
        )
        additional_evidence.append(uploaded)
        image_evidence_ids.append(uploaded.evidence_id)
        if photo.quality.issues:
            quality_source = EvidenceSource(
                source_type="user_image", trust_level="unrated", provider="pillow_image_quality",
                uri=image_source.uri, retrieved_at=image_source.retrieved_at,
            )
            additional_sources.append(quality_source)
            quality_item = Evidence(
                source_id=quality_source.source_id, evidence_type="visual_observation",
                subject="image_quality", observation="Image quality check: " + "; ".join(photo.quality.issues),
                exact_claim="image_quality: " + "; ".join(photo.quality.issues),
                source_url=quality_source.uri, retrieved_at=quality_source.retrieved_at,
                provider=quality_source.provider, supporting_text="; ".join(photo.quality.issues),
                confidence=1.0, source_trust_level="unrated",
            )
            additional_evidence.append(quality_item)
            quality_evidence_ids.append(quality_item.evidence_id)
    submission_source_map = {source.source_id: source for source in submission_sources}
    submitted_evidence = [
        _copy_with_source_metadata(
            item, submission_source_map[item.source_id],
            confidence=submission.candidate.field_confidence.get(item.subject),
        ) for item in submission.evidence
    ]
    known_submitted_fields = {(item.source_id, item.subject) for item in submitted_evidence}
    for raw_item in list(submitted_evidence):
        if raw_item.subject != "ocr_text":
            continue
        source = submission_source_map[raw_item.source_id]
        source_text = raw_item.supporting_text or raw_item.observation
        for field, pattern in ATTRIBUTE_PATTERNS.items():
            if (source.source_id, field) in known_submitted_fields:
                continue
            match = pattern.search(source_text)
            if not match:
                continue
            excerpt = match.group(0)
            submitted_evidence.append(Evidence(
                source_id=source.source_id, evidence_type="text_observation", subject=field,
                observation=f"OCR text explicitly contains {excerpt}",
                exact_claim=f"{field}: {_normalized_value(field, excerpt)}",
                source_url=source.uri, retrieved_at=source.retrieved_at,
                provider=source.provider, supporting_text=excerpt,
                confidence=raw_item.confidence, source_trust_level=source.trust_level,
                derived_from_evidence_ids=[raw_item.evidence_id],
            ))
            known_submitted_fields.add((source.source_id, field))
    external_sources: list[EvidenceSource] = []
    external_evidence: list[Evidence] = []
    if research_report:
        external_sources, external_evidence = normalize_search_report(research_report)

    sources = submission_sources + additional_sources + external_sources
    evidence = submitted_evidence + additional_evidence + external_evidence
    evidence_by_id = {item.evidence_id: item for item in evidence}
    submitted_values: dict[str, tuple[str, list[str]]] = {}
    for field in COMPARE_FIELDS:
        value = getattr(submission.candidate, field, None)
        refs = submission.candidate.field_evidence_ids.get(field, [])
        if value:
            submitted_values[field] = (str(value), refs)
    for key, value in submission.candidate.other_identifiers.items():
        field = key.casefold().replace("_", "")
        field = {"serialnumber": "serial", "barcode": "barcode", "ean": "ean", "upc": "upc"}.get(field, field)
        if field in COMPARE_FIELDS and value:
            submitted_values.setdefault(field, (value, submission.candidate.field_evidence_ids.get(key, [])))
    for item in submitted_evidence:
        if item.subject in COMPARE_FIELDS and item.exact_claim:
            submitted_values.setdefault(item.subject, (_claim_value(item), [item.evidence_id]))

    external_by_field: dict[str, list[Evidence]] = defaultdict(list)
    for item in external_evidence:
        if item.subject in COMPARE_FIELDS and item.exact_claim:
            external_by_field[item.subject].append(item)

    comparisons: list[EvidenceComparison] = []
    for field in ("listing_title", "seller_name", "listing_url"):
        refs = [item.evidence_id for item in additional_evidence if item.subject == field]
        if refs:
            comparisons.append(EvidenceComparison(
                dimension=field, result="unknown", evidence_status="not_yet_checked",
                explanation="User-provided listing information has not been independently verified.",
                evidence_ids=refs, submitted_value=listing_values[field],
            ))
    if image_evidence_ids and not any(source.source_type == "vision_output" for source in sources):
        comparisons.append(EvidenceComparison(
            dimension="uploaded_image_observations", result="unknown",
            evidence_status="not_yet_checked",
            explanation="Photos are recorded, but a vision provider has not analyzed product details.",
            evidence_ids=image_evidence_ids,
        ))
    if quality_evidence_ids:
        comparisons.append(EvidenceComparison(
            dimension="image_quality", result="insufficient_evidence",
            evidence_status="insufficient_evidence",
            explanation="Photo quality issues may limit product-detail inspection; they are not authenticity concerns.",
            evidence_ids=quality_evidence_ids,
        ))
    research_checked = bool(research_report and research_report.queries)
    report_status = "complete" if research_checked else "not_yet_checked"
    for field in COMPARE_FIELDS:
        submitted = submitted_values.get(field)
        if not submitted:
            contextual_refs = list(dict.fromkeys(image_evidence_ids))
            comparisons.append(EvidenceComparison(
                dimension=field, result="unknown", evidence_status="not_yet_checked",
                explanation="No submitted observation is available for comparison.",
                evidence_ids=contextual_refs,
            ))
            continue
        submitted_value, submitted_refs = submitted
        if not research_checked:
            comparisons.append(EvidenceComparison(
                dimension=field, result="unknown", evidence_status="not_yet_checked",
                explanation="External research has not been run for this check.",
                evidence_ids=_evidence_lineage(submitted_refs, evidence_by_id),
                submitted_value=submitted_value,
            ))
            continue
        found = external_by_field.get(field, [])
        if not found:
            comparisons.append(EvidenceComparison(
                dimension=field, result="unknown", evidence_status="not_found",
                explanation="Research completed, but no external evidence for this attribute was found.",
                evidence_ids=_evidence_lineage(submitted_refs, evidence_by_id),
                submitted_value=submitted_value,
            ))
            continue
        ranked = [(TRUST_RANK.get(item.source_trust_level or "unrated", 0), item) for item in found]
        best_rank = max(rank for rank, _ in ranked)
        strongest = [item for rank, item in ranked if rank == best_rank]
        values = {_claim_value(item).casefold() for item in strongest}
        all_refs = list(dict.fromkeys(
            _evidence_lineage(submitted_refs, evidence_by_id)
            + _evidence_lineage([item.evidence_id for item in found], evidence_by_id)
        ))
        weaker_refs: list[str] = []
        if best_rank < TRUST_RANK["medium"]:
            result = "insufficient_evidence"
            status = "insufficient_evidence"
            explanation = "Only low-trust or unrated external sources mention this attribute."
        elif len(values) > 1:
            result = "insufficient_evidence"
            status = "insufficient_evidence"
            explanation = "The strongest available sources conflict on this attribute."
            weaker_refs = [item.evidence_id for item in strongest]
        else:
            external_value = _claim_value(strongest[0])
            matches = external_value.casefold() == submitted_value.casefold()
            weaker_refs = [
                item.evidence_id for rank, item in ranked
                if rank < best_rank and _claim_value(item).casefold() != external_value.casefold()
            ]
            result = "match" if matches else "mismatch"
            status = None if matches else "contradicted"
            explanation = "The strongest available source agrees with the submitted observation." if matches else "The strongest available source explicitly differs from the submitted observation."
            if weaker_refs:
                explanation += " Lower-trust sources differ and were not allowed to override it."
        external_value = _claim_value(strongest[0]) if len(values) == 1 else None
        comparisons.append(EvidenceComparison(
            dimension=field, result=result, evidence_status=status, explanation=explanation,
            evidence_ids=all_refs, conflicting_evidence_ids=weaker_refs,
            submitted_value=submitted_value, external_value=external_value,
            source_trust_level=strongest[0].source_trust_level,
        ))

    return EvidenceReport(
        check_id=submission.check.check_id, status=report_status,
        evidence_sources=sources, evidence=evidence, comparisons=comparisons,
        generated_at=datetime.now(timezone.utc),
    )


def _claim_value(item: Evidence) -> str:
    claim = item.exact_claim or item.observation
    prefix = f"{item.subject}:"
    return claim[len(prefix):].strip() if claim.casefold().startswith(prefix.casefold()) else claim.strip()


def _evidence_lineage(refs: list[str], evidence_by_id: dict[str, Evidence]) -> list[str]:
    ordered: list[str] = []
    pending = list(refs)
    while pending:
        evidence_id = pending.pop(0)
        if evidence_id in ordered or evidence_id not in evidence_by_id:
            continue
        ordered.append(evidence_id)
        pending[0:0] = evidence_by_id[evidence_id].derived_from_evidence_ids
    return ordered
