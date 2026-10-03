# Veyro Architecture

## Sprint 3: traceable footwear evidence engine

Veyro verifies product authenticity. It is not a shopping recommendation or
product search engine. India and footwear are the initial market and category.
The single pipeline accepts real submissions, performs local image quality
checks and OCR, researches external product references, and produces a
rule-based categorical assessment. It does not calculate an authenticity
score or claim certainty.

The check flow is:

```
listing + photos
  -> image quality + OCR evidence
  -> candidate identity + quality guidance
  -> explicit identify request
  -> official brand and India retailer search
  -> normalized, source-ranked evidence set
  -> submitted observation ↔ external evidence comparisons
  -> persisted explainable evidence report
  -> rule-based assessment with cited findings
```

### Domain

- `AuthenticityCheck` records the submitted listing/photo references and
  constrains the initial market and category.
- `ProductIdentity` records a candidate brand, product, model, and variant.
  It includes OCR extraction confidence and evidence IDs per field; it is
  identification context, not an authenticity verdict.
- `EvidenceSource` records where evidence came from, its provider, URI, market,
  retrieval time, source type, and independent trust level.
- `Evidence` records an exact claim, supporting text, extraction confidence,
  source URL/provider/retrieval time and source trust level, and points to
  exactly one source. Raw source snippets remain in the evidence set alongside
  normalized attribute claims.
- `EvidenceComparison` records `match`, `mismatch`, `unknown`, or
  `insufficient_evidence`, plus a separate state for `not_found`,
  `contradicted`, or `not_yet_checked`. Comparison references resolve to
  evidence IDs in the report.
- `EvidenceReport` is the combined, persisted submission and external evidence
  trail for a check. Pydantic validation rejects missing sources and dangling
  evidence references.
- `AssessmentFinding` classifies a cited finding as supporting, concerning,
  contradictory, unknown, or insufficient evidence.
- `AuthenticityAssessment` contains a categorical overall assessment,
  qualitative confidence with its basis, supporting findings, concerns,
  contradictions, missing evidence, product identity, comparisons, and the
  evidence/source records needed to resolve every reference.

Pydantic validation rejects an assessment if a finding, comparison, or
normalized observation points to evidence absent from the report. Evidence
that points to an absent source is rejected as well.

### Submission API and storage

POST /v1/authenticity/checks accepts JSON metadata in a multipart form field
and multiple photos files. JPEG, PNG, and WebP are allowed; each photo is
limited to 10 MB, up to eight photos, and 40 MB total. The actual image format
is inspected rather than trusting the uploaded MIME type.

Images are written to local storage and submission/OCR metadata to SQLite.
Set VEYRO_DATA_DIR to a durable writable volume in deployment. Uploads use
random IDs; client filenames are metadata only.

### OCR and image quality

OCRProvider, VisionProvider, and ImageQualityProvider are replaceable
contracts. The default OCR adapter invokes the Tesseract system executable.
Pillow validates images and reports low resolution, extreme brightness, and
low edge detail. OCR text is parsed conservatively for known brand names and
labeled model/SKU/style/size/color/serial/barcode fields. Each extracted field
gets an evidence record tied to the submitted image and an OCR confidence.
Conflicting values across images are left unset and reported.

If Tesseract is unavailable or cannot read an image, the submission is still
stored; status and guidance make the failure explicit. No missing value is
filled from a brand catalogue or a sample product.

### External product research

`SubmissionProductIdentificationProvider` accepts a stored submission and
returns a `ProductIdentificationReport`. `ProductResearchProvider` creates
separate brand/model, code, colourway, official-domain, and known-retailer
queries, then consumes a `WebSearchClient`. `BraveSearchClient` is the default
adapter. It uses the documented authenticated JSON endpoint and does not fetch
or parse result pages. Credentials come from `BRAVE_SEARCH_API_KEY`; there is no
fallback dataset or sample response.

Search result title and description are preserved as observations and
normalized conservatively for product/model, SKU/style, colourway, size,
materials/specifications, packaging/label text and identifiers where explicit
text is available. Results from recognized brand domains are `official_brand`
with `very_high` trust. Authorized retailer domains must be explicitly configured
with `VEYRO_AUTHORISED_RETAILER_DOMAINS` and receive `high` trust. Known
marketplaces receive `medium` trust, and other web domains receive `low` trust.
Source type and trust level are separate values.

Comparisons use the strongest source tier available for an attribute. Weaker
sources cannot override stronger sources. Conflicts within the strongest tier
and claims supported only by low-trust or unrated sources produce
`insufficient_evidence`. A completed search with no attribute claim returns
`unknown` / `not_found`; before external research the comparison is
`unknown` / `not_yet_checked`. An explicit stronger-source difference is
`mismatch` / `contradicted`. Missing evidence never creates a counterfeit
claim. Evidence extraction confidence describes text extraction, not product
authenticity probability.

Research and complete evidence reports are stored in SQLite alongside the
submission.
Search is explicitly triggered with POST
`/v1/authenticity/checks/{check_id}/identify`; missing credentials return a
service configuration error. `ProductResearchProvider` and `WebSearchClient`
can be replaced without changing the submission pipeline. GET
`/v1/authenticity/checks/{check_id}/evidence` returns the stored evidence report
or a persisted `not_yet_checked` report before research runs.

GET `/v1/authenticity/checks/{check_id}/assessment` builds an assessment from
the persisted evidence report when needed, then stores the result in SQLite.
Likely-authentic requires high-trust agreement across brand, model/product name,
and a unique SKU/style identifier with no strong contradictions. A high-trust
explicit model/SKU/style contradiction supports likely-counterfeit unless
authoritative evidence conflicts. Conflicting authoritative sources and all
other patterns remain inconclusive. Every finding cites evidence IDs. Missing
fields stay unknown and cannot independently support a counterfeit assessment.
Confidence is a qualitative evidence-coverage label, not a validated
probability or accuracy measure. This is deterministic rule logic, not a
machine-learning classifier.

### Remaining workflow

Further photo-view classification, richer catalogue integrations, page-level
verification of search snippets, source authorization maintenance, and
assessment calibration remain future steps. The React + Vite frontend is a
local developer test UI, not a production deployment. The assessment does not
calculate a numeric authenticity score. Evidence ID references establish
structural traceability; they do not prove provider observations are truthful.
# Image analysis providers

Uploaded images pass through image-quality checks, the OCR provider, and the
replaceable `VisionProvider` before product identification research. The
Gemini and OpenAI implementations conform to the same `VisionProvider`.
`VISION_PROVIDER` selects the implementation and defaults to `gemini`. The
Gemini adapter uses the Interactions API with image input and a JSON schema;
`GEMINI_VISION_MODEL` defaults to `gemini-3.1-flash-lite` and credentials come
from `GEMINI_API_KEY`. The OpenAI adapter uses the Responses API;
`OPENAI_VISION_MODEL` defaults to `gpt-6-luna` and credentials come from
`OPENAI_API_KEY`. Both emit
per-image evidence for explicitly visible brand, model, SKU/style code,
colourway, labels, packaging, markings, and physical observations. Every claim
retains a visual basis and provider-reported extraction confidence. Unobserved
fields are omitted. No assessment rule or threshold is modified by image
analysis.

OCR uses the local Tesseract executable by default; `VEYRO_TESSERACT_CMD` can
select a different executable path. External research remains on the Brave
provider using `BRAVE_SEARCH_API_KEY`. Missing provider credentials are
surfaced as unavailable stages and do not introduce guessed evidence.
