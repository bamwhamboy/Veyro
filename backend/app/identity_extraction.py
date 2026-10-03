"""Conservative structured field extraction from OCR text."""
from __future__ import annotations

import re
from collections import defaultdict

from .domain import Evidence, ProductIdentity

_BRANDS = (
    "New Balance", "Skechers", "Adidas", "ASICS", "Nike", "Puma", "Crocs",
    "Reebok", "Converse", "Vans", "Campus",
)
_FIELD_PATTERNS = {
    "product_name": re.compile(
        r"\b(?:product\s+name|model\s+name)\s*[:#-]?\s*"
        r"([A-Za-z0-9][A-Za-z0-9 .&'/-]{2,50}?)"
        r"(?=\s+(?:MODEL|SKU|STYLE|SIZE|COLOUR|COLOR|UPC|EAN|SERIAL)\b|$)",
        re.IGNORECASE,
    ),
    "model_number": re.compile(
        r"\bmodel(?!\s+name)(?:\s*(?:no\.?|number|#))?\s*[:#-]?\s*"
        r"([A-Z0-9][A-Z0-9./-]{2,})",
        re.IGNORECASE,
    ),
    "sku": re.compile(
        r"\bSKU\s*[:#-]?\s*([A-Z0-9][A-Z0-9./-]{2,})", re.IGNORECASE
    ),
    "style_code": re.compile(
        r"\b(?:style(?:\s*code)?|article\s*(?:no\.?|number))"
        r"\s*[:#-]?\s*([A-Z0-9][A-Z0-9./-]{2,})",
        re.IGNORECASE,
    ),
    "size": re.compile(
        r"\b(?:size\s*[:#-]?\s*"
        r"((?:(?:US|UK|EU|EUR|CM)\s*)?[0-9]{1,2}(?:\.[05])?)|"
        r"(US|UK|EU|EUR|CM)\s*(?:size\s*)?([0-9]{1,2}(?:\.[05])?))\b",
        re.IGNORECASE,
    ),
    "colorway": re.compile(
        r"\bcolou?r\s*[:#-]?\s*"
        r"([A-Za-z][A-Za-z/-]*(?:\s+[A-Za-z][A-Za-z/-]*){0,2})"
        r"(?=\s+(?:UPC|EAN|SKU|STYLE|MODEL|SIZE|SERIAL)\b|$)",
        re.IGNORECASE,
    ),
}
_IDENTIFIER_PATTERN = re.compile(
    r"\b(UPC|EAN|barcode|serial(?:\s*(?:no\.?|number))?)"
    r"\s*[:#-]?\s*([A-Z0-9-]{4,})",
    re.IGNORECASE,
)


def extract_identity(
    text: str, *, confidence: float | None, source_id: str,
    raw_evidence_id: str | None = None,
) -> tuple[ProductIdentity, list[Evidence]]:
    """Return only fields explicitly found in OCR output, each with evidence."""
    normalized_text = re.sub(r"\s+", " ", text).strip()
    if not normalized_text:
        return ProductIdentity(), []

    found: dict[str, tuple[str, str]] = {}
    brand = next(
        (
            item for item in _BRANDS
            if re.search(rf"(?<![A-Za-z]){re.escape(item)}(?![A-Za-z])",
                         normalized_text, re.IGNORECASE)
        ),
        None,
    )
    if brand:
        match = re.search(
            rf"(?<![A-Za-z]){re.escape(brand)}(?![A-Za-z])",
            normalized_text,
            re.IGNORECASE,
        )
        found["brand"] = (brand, match.group(0))

    for field, pattern in _FIELD_PATTERNS.items():
        match = pattern.search(normalized_text)
        if match:
            if field == "size":
                value = match.group(1) or f"{match.group(2).upper()} {match.group(3)}"
            else:
                value = match.group(1).strip(" .,:;")
            if value:
                found[field] = (value, match.group(0))

    identifiers: dict[str, tuple[str, str]] = {}
    for match in _IDENTIFIER_PATTERN.finditer(normalized_text):
        key = re.sub(r"\s+", "_", match.group(1).lower()).replace(".", "")
        identifiers[key] = (match.group(2), match.group(0))

    evidence: list[Evidence] = []
    field_evidence_ids: dict[str, list[str]] = {}
    for field, (value, excerpt) in found.items():
        item = Evidence(
            source_id=source_id,
            evidence_type="text_observation",
            subject=field,
            observation=f"OCR read “{excerpt}”.",
            exact_claim=f"{field}: {value}",
            supporting_text=excerpt,
            confidence=round(confidence or 0.0, 4),
            derived_from_evidence_ids=[raw_evidence_id] if raw_evidence_id else [],
        )
        evidence.append(item)
        field_evidence_ids[field] = [item.evidence_id]

    other_identifiers: dict[str, str] = {}
    for field, (value, excerpt) in identifiers.items():
        other_identifiers[field] = value
        item = Evidence(
            source_id=source_id,
            evidence_type="text_observation",
            subject=field,
            observation=f"OCR read “{excerpt}”.",
            exact_claim=f"{field}: {identifiers[field][0]}",
            supporting_text=excerpt,
            confidence=round(confidence or 0.0, 4),
            derived_from_evidence_ids=[raw_evidence_id] if raw_evidence_id else [],
        )
        evidence.append(item)
        field_evidence_ids[field] = [item.evidence_id]

    field_confidence = {
        field: round(confidence or 0.0, 4) for field in field_evidence_ids
    }
    populated_fields = {
        "brand": found.get("brand", (None, None))[0],
        "product_name": found.get("product_name", (None, None))[0],
        "model_number": found.get("model_number", (None, None))[0],
        "sku": found.get("sku", (None, None))[0],
        "style_code": found.get("style_code", (None, None))[0],
        "size": found.get("size", (None, None))[0],
        "colorway": found.get("colorway", (None, None))[0],
    }
    all_evidence_ids = [item.evidence_id for item in evidence]
    overall_confidence = (
        sum(field_confidence.values()) / len(field_confidence)
        if field_confidence
        else 0.0
    )
    return (
        ProductIdentity(
            **populated_fields,
            other_identifiers=other_identifiers,
            confidence=round(overall_confidence, 4),
            field_confidence=field_confidence,
            evidence_ids=all_evidence_ids,
            field_evidence_ids=field_evidence_ids,
        ),
        evidence,
    )


def extract_visual_identity(evidence: list[Evidence]) -> ProductIdentity:
    """Build identity fields only from explicit structured visual claims."""
    subject_fields = {
        "brand": "brand",
        "product_name": "product_name",
        "model_number": "model_number",
        "sku": "sku",
        "style_code": "style_code",
        "colorway": "colorway",
        "size": "size",
    }
    values: dict[str, list[tuple[str, Evidence]]] = defaultdict(list)
    for item in evidence:
        field = subject_fields.get(item.subject)
        if field is None:
            continue
        claim = item.exact_claim or ""
        prefix = f"{item.subject}:"
        if not claim.casefold().startswith(prefix.casefold()):
            continue
        value = claim[len(prefix):].strip()
        if value:
            values[field].append((value, item))

    identity_values: dict[str, str | None] = {}
    field_confidence: dict[str, float] = {}
    field_evidence_ids: dict[str, list[str]] = {}
    for field in subject_fields.values():
        observations = values.get(field, [])
        if len({value.casefold() for value, _ in observations}) != 1:
            identity_values[field] = None
            continue
        identity_values[field] = observations[0][0]
        field_evidence_ids[field] = [item.evidence_id for _, item in observations]
        confidences = [item.confidence for _, item in observations if item.confidence is not None]
        if confidences:
            field_confidence[field] = round(sum(confidences) / len(confidences), 4)

    evidence_ids = list(dict.fromkeys(
        ref for refs in field_evidence_ids.values() for ref in refs
    ))
    confidence = sum(field_confidence.values()) / len(field_confidence) if field_confidence else 0.0
    return ProductIdentity(
        **identity_values,
        confidence=round(confidence, 4),
        field_confidence=field_confidence,
        evidence_ids=evidence_ids,
        field_evidence_ids=field_evidence_ids,
    )


def merge_identity_candidates(
    candidates: list[ProductIdentity], evidence: list[Evidence]
) -> tuple[ProductIdentity, list[str]]:
    """Keep fields only when uploaded images provide one unambiguous value."""
    scalar_fields = (
        "brand", "product_name", "model_number", "sku", "style_code", "size",
        "colorway",
    )
    merged: dict[str, object] = {}
    field_confidence: dict[str, float] = {}
    field_evidence_ids: dict[str, list[str]] = {}
    conflicts: list[str] = []

    for field in scalar_fields:
        observed = [(getattr(candidate, field), candidate) for candidate in candidates]
        observed = [(value, candidate) for value, candidate in observed if value]
        unique_values = {str(value).casefold() for value, _ in observed}
        if len(unique_values) > 1:
            conflicts.append(field)
            continue
        if not observed:
            merged[field] = None
            continue
        value = observed[0][0]
        merged[field] = value
        source_candidates = [
            candidate for candidate in candidates
            if field in candidate.field_evidence_ids
        ]
        refs = list(dict.fromkeys(
            ref for candidate in source_candidates
            for ref in candidate.field_evidence_ids[field]
        ))
        if refs:
            field_evidence_ids[field] = refs
            field_confidence[field] = max(
                candidate.field_confidence.get(field, 0.0)
                for candidate in source_candidates
            )

    identifier_values: dict[str, set[str]] = defaultdict(set)
    identifier_refs: dict[str, list[str]] = defaultdict(list)
    identifier_confidence: dict[str, list[float]] = defaultdict(list)
    for candidate in candidates:
        for field, value in candidate.other_identifiers.items():
            identifier_values[field].add(value.casefold())
            identifier_refs[field].extend(candidate.field_evidence_ids.get(field, []))
            identifier_confidence[field].append(candidate.field_confidence.get(field, 0.0))

    other_identifiers: dict[str, str] = {}
    for field, values in identifier_values.items():
        if len(values) > 1:
            conflicts.append(field)
            continue
        other_identifiers[field] = next(
            value for candidate in candidates
            for key, value in candidate.other_identifiers.items()
            if key == field
        )
        refs = list(dict.fromkeys(identifier_refs[field]))
        if refs:
            field_evidence_ids[field] = refs
            field_confidence[field] = max(identifier_confidence[field])

    all_evidence_ids = list(dict.fromkeys(
        evidence_id for candidate in candidates
        for evidence_id in candidate.evidence_ids
    ))
    overall_confidence = (
        sum(field_confidence.values()) / len(field_confidence)
        if field_confidence else 0.0
    )
    return ProductIdentity(
        **merged,
        other_identifiers=other_identifiers,
        confidence=round(overall_confidence, 4),
        field_confidence=field_confidence,
        evidence_ids=all_evidence_ids,
        field_evidence_ids=field_evidence_ids,
    ), conflicts
