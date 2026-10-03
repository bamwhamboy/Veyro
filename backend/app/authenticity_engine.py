"""Transparent rule-based authenticity assessment over the evidence report."""
from __future__ import annotations

from datetime import datetime, timezone

from .domain import (
    AssessmentFinding,
    AuthenticityAssessment,
    EvidenceReport,
    VerificationSubmission,
)

TRUST_RANK = {"unrated": 0, "low": 1, "medium": 2, "high": 3, "very_high": 4}
CORE_IDENTITY_FIELDS = {"brand", "product_name", "model_number", "sku", "style_code"}


def build_authenticity_assessment(
    submission: VerificationSubmission,
    report: EvidenceReport,
) -> AuthenticityAssessment:
    """Produce a cautious categorical conclusion; confidence is qualitative only."""
    if submission.check.check_id != report.check_id:
        raise ValueError("Evidence report does not belong to the supplied check")

    evidence_by_id = {item.evidence_id: item for item in report.evidence}
    supporting: list[AssessmentFinding] = []
    concerns: list[AssessmentFinding] = []
    contradictions: list[AssessmentFinding] = []
    missing: list[AssessmentFinding] = []
    strong_mismatch_dimensions: set[str] = set()
    strong_matches: set[str] = set()
    authoritative_conflict = False

    for comparison in report.comparisons:
        evidence_ids = list(dict.fromkeys(
            ref for ref in [*comparison.evidence_ids, *comparison.conflicting_evidence_ids]
            if ref in evidence_by_id
        ))
        if not evidence_ids:
            continue
        trust = comparison.source_trust_level or max(
            (evidence_by_id[ref].source_trust_level or "unrated" for ref in evidence_ids),
            key=lambda level: TRUST_RANK[level],
        )
        dimension = comparison.dimension
        if comparison.result == "match":
            supporting.append(AssessmentFinding(
                dimension=dimension, classification="supporting",
                statement=comparison.explanation, evidence_ids=evidence_ids,
                source_trust_level=trust,
            ))
            if dimension in CORE_IDENTITY_FIELDS and TRUST_RANK[trust] >= TRUST_RANK["high"]:
                strong_matches.add(dimension)
        elif comparison.result == "mismatch":
            strong = TRUST_RANK[trust] >= TRUST_RANK["high"]
            finding = AssessmentFinding(
                dimension=dimension,
                classification="contradictory" if strong else "concerning",
                statement=comparison.explanation, evidence_ids=evidence_ids,
                source_trust_level=trust,
            )
            (contradictions if strong else concerns).append(finding)
            if strong and dimension in {"model_number", "sku", "style_code"}:
                strong_mismatch_dimensions.add(dimension)
        else:
            classification = "insufficient_evidence" if comparison.result == "insufficient_evidence" else "unknown"
            missing.append(AssessmentFinding(
                dimension=dimension, classification=classification,
                statement=comparison.explanation, evidence_ids=evidence_ids,
                source_trust_level=trust,
            ))
            if (comparison.result == "insufficient_evidence"
                    and TRUST_RANK[trust] >= TRUST_RANK["high"]):
                authoritative_conflict = True

    # A single high-trust contradiction in an identifying code is decisive as a
    # concern, unless strong sources conflict with each other on another check.
    if authoritative_conflict:
        overall = "inconclusive"
    elif strong_mismatch_dimensions:
        overall = "likely_counterfeit"
    elif _has_core_support(strong_matches) and not concerns and not contradictions:
        overall = "likely_authentic"
    else:
        overall = "inconclusive"

    if overall == "likely_authentic":
        confidence = "moderate" if missing else "high"
        summary = (
            "High-trust references consistently support the submitted brand, product identity, "
            "and identifying code. This is a likely-authentic assessment, not a certainty."
        )
        basis = "Rule-based confidence is high only when multiple high-trust identity fields agree; missing checks lower it to moderate. It is not a probability."
    elif overall == "likely_counterfeit":
        confidence = "moderate"
        summary = (
            "A high-trust reference explicitly contradicts a submitted model or identifying code. "
            "This supports a likely-counterfeit assessment, not a certainty."
        )
        basis = "Rule-based confidence is moderate because at least one high-trust core identifier conflicts. It is not a probability."
    else:
        confidence = "moderate" if supporting or concerns or contradictions else "low"
        summary = (
            "The available evidence does not support a clear likely-authentic or likely-counterfeit "
            "assessment. Missing or conflicting evidence remains unresolved."
        )
        basis = "Rule-based confidence is qualitative and reflects evidence coverage and source agreement. It is not a probability."

    all_findings = [*supporting, *concerns, *contradictions, *missing]
    assessment_evidence_ids = list(dict.fromkeys(
        evidence_id for finding in all_findings for evidence_id in finding.evidence_ids
    ))
    return AuthenticityAssessment(
        check_id=submission.check.check_id,
        overall_assessment=overall,
        confidence=confidence,
        confidence_basis=basis,
        summary=summary,
        supporting_findings=supporting,
        concerns=concerns,
        contradictions=contradictions,
        missing_evidence=missing,
        evidence_ids=assessment_evidence_ids,
        evidence_sources=report.evidence_sources,
        evidence=report.evidence,
        comparisons=report.comparisons,
        assessed_at=datetime.now(timezone.utc),
        identity=submission.candidate,
    )


def _has_core_support(fields: set[str]) -> bool:
    """Require brand, model/name, and a unique SKU/style identifier."""
    has_brand = "brand" in fields
    has_model = bool(fields & {"product_name", "model_number"})
    has_code = bool(fields & {"sku", "style_code"})
    return has_brand and has_model and has_code
