# Product Direction

## Veyro

Veyro is an AI-powered product authenticity verification platform. The initial
scope is footwear sold in India.

## Problem

Buyers need help assessing whether a listed or purchased shoe is consistent
with reliable product evidence. Listing copy and seller assertions alone do
not prove authenticity. Veyro should compare product identity and physical
observations with traceable evidence, then explain what supports or raises
concern and where the evidence came from.

## Check workflow

1. The user submits a product listing and photos.
2. A provider identifies a candidate product identity.
3. Replaceable providers collect source-attributed evidence from web pages,
   OCR, vision, and brand/catalogue sources.
4. Evidence is compared across listing details, observed product details, and
   trusted references.
5. The assessment provider produces a calibrated verdict and claims.
6. Veyro returns a report where each conclusion and claim cites evidence IDs.

## Product principles

- A candidate product identity is not itself an authenticity decision.
- User-submitted claims and provider observations remain distinguishable.
- Missing information stays unknown; Veyro does not infer evidence.
- Every report claim is traceable to an evidence record and source.
- Provider choices remain replaceable behind small interfaces.
- The verification work remains a single pipeline; it does not introduce
  autonomous agents.

## Sprint boundaries

Sprint 1 accepts listing metadata and multiple photos, stores submissions,
checks image quality, and extracts visible text with a replaceable OCR
provider. OCR-derived fields carry supporting evidence IDs and extraction
confidence. Unavailable or ambiguous fields remain unset.

Sprint 2 adds an explicit external identification step through a replaceable
web search adapter. It prioritizes official brand queries, searches model,
style/SKU and colourway signals, and records returned page metadata as
source-linked evidence. Search-result text can support identity matches or
explicit labeled-code contradictions; absent data stays unknown. This is not
page-level catalogue verification, a trust policy, or an authenticity verdict.

Sprint 3 adds a persisted evidence report that retains source type, source trust,
exact normalized claims, supporting snippets, retrieval time, provider and
extraction confidence. Comparisons distinguish matches, explicit mismatches,
missing external claims, unchecked comparisons and conflicting/weak evidence.
Official sources outrank authorized retailers, which outrank established
marketplaces and other web sources. Lower-trust claims cannot override higher
trust claims. No authenticity score or verdict is produced, and absence of
evidence is never treated as evidence of counterfeit.

Sprint 4 adds a deterministic assessment over that evidence trail. It returns
likely_authentic only when high-trust references agree across brand,
product/model, and a unique SKU/style identifier without strong contradictions.
An explicit high-trust identifier contradiction can support likely_counterfeit;
conflicting authoritative evidence and other patterns remain inconclusive.
Findings cite evidence IDs, and confidence is qualitative rather than a
scientifically validated probability. Missing evidence alone cannot indicate
counterfeit.

Sprint 5 adds a minimal local React + Vite developer UI for submitting real
photos and viewing identity, assessment, and traceable evidence. Gemini and
OpenAI vision providers are replaceable and selected with configuration.

Further photo-view classification, richer source verification, live provider
validation, and assessment calibration remain future work.
