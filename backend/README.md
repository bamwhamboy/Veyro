# Backend

Sprint 3 backend for Veyro's India footwear authenticity verification flow.

```
submission API -> image storage + SQLite metadata -> image quality + OCR + vision -> evidence-linked identity
identify API -> replaceable research provider -> Brave Search JSON API -> source-linked external evidence and identity comparisons
```

The submission API is POST /v1/authenticity/checks. Send metadata as a JSON
multipart form field and attach one or more files under the repeated photos
field. JPEG, PNG, and WebP are supported. The response includes quality
reports, OCR and vision status, extracted candidate identity, field confidence,
source-linked observations, evidence IDs, and retake guidance.

The default OCR adapter uses the Tesseract executable. Install it on the host
to enable OCR; when unavailable, uploads are stored and returned with OCR
status unavailable and no inferred fields. Set VEYRO_DATA_DIR to a persistent
writable directory; it holds images and a SQLite metadata database. OCR and
vision adapters remain replaceable through contracts in app/providers.py.

Call POST /v1/authenticity/checks/{check_id}/identify to research the identity
candidate from a stored submission. Configure `BRAVE_SEARCH_API_KEY` in the
process environment. Search calls use the provider's documented JSON response;
the application does not scrape result pages. Official brand domains receive
priority queries. Known Indian retailer domains are classified as retailer
references; other results remain generic web sources. Results, query strings,
evidence and retrieval times are returned and stored in SQLite. Identity
comparisons distinguish matched values, unobserved values and explicitly
labeled conflicting model/style/SKU codes. This is product identification only,
not an authenticity assessment.

Retrieve the accumulated source-linked evidence and comparisons with GET
`/v1/authenticity/checks/{check_id}/evidence`. A pre-research report labels
comparisons `not_yet_checked`. After research, absent attributes are
`not_found` with an `unknown` result; this is never a mismatch. The evidence
report persists original snippets, normalized claims, source URLs, retrieval
times, provider names, extraction confidence, source type and trust tier.
Official brand sources have very high trust; explicitly configured
authorised-retailer sources have high trust; established marketplaces have
medium trust; other web sources have low trust. Set
`VEYRO_AUTHORISED_RETAILER_DOMAINS` to a comma-separated list
only when those retailers' authorization has been verified. Conflicts among
strongest sources, or claims supported only by low-trust sources, return
`insufficient_evidence`.

GET `/v1/authenticity/checks/{check_id}/assessment` returns and persists a
deterministic, evidence-based assessment. Likely-authentic requires high-trust
agreement across brand, product/model, and a SKU/style identifier, with no
strong contradictions. A high-trust explicit model/SKU/style contradiction
supports likely-counterfeit unless authoritative evidence conflicts. All other
cases remain inconclusive. Confidence is qualitative (`low`, `moderate`, or
`high`) with an explanation; it is not a probability or validated accuracy
measure. Every finding links to included evidence. Missing information never
creates a counterfeit conclusion. This is a rule engine, not a trained
classifier.

Python 3.12 or newer is required. With `uv`, run `uv sync --extra dev` and
`uv run pytest`.

## Developer test UI

The React + Vite app in `../frontend` exercises the existing submission,
identification, evidence, and assessment APIs. Start this API with
`uv run uvicorn app.main:app --reload`, then run `npm install && npm run dev`
from the frontend directory. The API allows `http://localhost:5173` and
`http://127.0.0.1:5173` for local browser access. Set `VEYRO_CORS_ORIGINS` to
a comma-separated list to configure other development origins.
# Local provider configuration

The submission flow runs Tesseract OCR and Gemini or OpenAI image analysis through
replaceable `OCRProvider` and `VisionProvider` interfaces. Install Tesseract
locally (`brew install tesseract` on macOS or
`sudo apt-get install tesseract-ocr` on Debian/Ubuntu). The default executable
name is `tesseract`; set `VEYRO_TESSERACT_CMD` if it is installed elsewhere.

Configure these variables in the backend process environment:

| Variable | Required for | Default |
| --- | --- | --- |
| `VISION_PROVIDER` | Select `gemini` or `openai` | `gemini` |
| `GEMINI_API_KEY` | Gemini vision analysis | unset; vision is marked unavailable |
| `GEMINI_VISION_MODEL` | Select the Gemini Interactions API model | `gemini-3.1-flash-lite` |
| `OPENAI_API_KEY` | OpenAI vision analysis when selected | unset |
| `OPENAI_VISION_MODEL` | Select the OpenAI Responses API model | `gpt-6-luna` |
| `BRAVE_SEARCH_API_KEY` | External product research | unset; research reports an unconfigured provider |
| `VEYRO_TESSERACT_CMD` | Override Tesseract executable | `tesseract` from PATH |
| `VEYRO_DATA_DIR` | Persistent local image/database storage | `var` |

The selected adapter sends uploaded JPEG, PNG, or WebP image bytes to the
Gemini Interactions API or OpenAI Responses API and requests structured output.
Gemini is selected by default for local experimentation. Each explicit observation
retains its image source, visual basis, timestamp, provider, and model-reported
extraction confidence. Empty or unreadable values are omitted; failures do not
produce substitute product details. Confidence is not an authenticity
probability. Tests inject a mocked transport and do not need provider keys.

For local Gemini development, export the keys before starting the API, for example:

```sh
export VISION_PROVIDER="gemini"
export GEMINI_API_KEY="..."
export BRAVE_SEARCH_API_KEY="..."
uv run uvicorn app.main:app --reload
```

In a second terminal, start the developer UI with `npm run dev` from
`frontend/`, upload real shoe photos, and submit. The submission response
contains the Gemini observations. Use “Identify product & gather evidence” to
continue through web research; that step also needs `BRAVE_SEARCH_API_KEY`.
Install Tesseract to enable OCR alongside vision.

To use OpenAI instead, set `VISION_PROVIDER=openai` and `OPENAI_API_KEY`;
`OPENAI_VISION_MODEL` can override its default model. `GEMINI_VISION_MODEL` can
override Gemini's default model. Keep credentials out of source control and
never expose them to the Vite frontend.
