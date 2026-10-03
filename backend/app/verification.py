"""Single-pipeline authenticity workflow. No provider is enabled by default."""
from __future__ import annotations

from .domain import (
    AuthenticityCheck,
    EvidenceBundle,
    PipelineAuthenticityAssessment,
)
from .providers import (
    AuthenticityAssessmentProvider,
    EvidenceComparisonProvider,
    EvidenceProvider,
    ProductIdentificationProvider,
)


def run_authenticity_check(
    check: AuthenticityCheck,
    *,
    identifier: ProductIdentificationProvider,
    evidence_providers: list[EvidenceProvider],
    comparer: EvidenceComparisonProvider,
    assessor: AuthenticityAssessmentProvider,
) -> PipelineAuthenticityAssessment:
    """Run identification -> evidence -> comparison -> evidence-linked verdict."""
    identification = identifier.identify(check)
    identity = identification.identity
    collected = [identification.evidence_bundle]
    collected.extend(provider.collect(check, identity) for provider in evidence_providers)

    bundle = EvidenceBundle(
        sources=[source for part in collected for source in part.sources],
        evidence=[item for part in collected for item in part.evidence],
    )
    comparisons = comparer.compare(identity, bundle.evidence)
    decision = assessor.assess(identity, bundle.evidence, comparisons)

    return PipelineAuthenticityAssessment(
        check_id=check.check_id,
        verdict=decision.verdict,
        outcome_evidence_ids=decision.outcome_evidence_ids,
        identity=identity,
        evidence_sources=bundle.sources,
        evidence=bundle.evidence,
        comparisons=comparisons,
        claims=decision.claims,
    )
