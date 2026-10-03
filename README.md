# Veyro

Veyro is an AI-powered product authenticity verification platform, starting
with footwear in India.

## Verification workflow

The current submission API accepts listing metadata and multiple footwear
photos. It stores image files and metadata, runs OCR and vision through
replaceable providers, checks image quality, and returns only fields supported
by extracted text or explicit visual observations with evidence references. A separate identification endpoint can query
Brave Search's JSON API for official brand pages and Indian retailer references,
then return source-linked identity matches and explicit code contradictions. It
does not make an authenticity verdict at that stage. A rule-based assessment
endpoint evaluates the persisted evidence report and returns a cautious
categorical assessment with cited findings. The evidence endpoint combines uploaded
observations and external claims, labels source trust separately from source
type, and reports matches, mismatches, not-found attributes, and unchecked
attributes without treating missing evidence as counterfeit evidence.

## Project structure

- `backend/` — domain models, provider contracts, and the single verification
  workflow
- `frontend/` — React + Vite developer UI for exercising the verification APIs
- `docs/` — product and architecture notes

OCR runs through Tesseract when the executable is installed. Vision uses a
configurable Gemini Interactions API or OpenAI Responses API provider. Web research uses
`BRAVE_SEARCH_API_KEY`; without it, the submission flow remains available and
the research endpoint reports that search is not configured. The rule-based
assessment API is available to the UI and is not a trained classifier.

## Development

The backend requires Python 3.12 or newer. With uv, run uv sync --extra dev
and then uv run pytest from backend/.

Set `VEYRO_DATA_DIR` to a persistent writable directory before serving the API.
The default is `backend/var` when launched from the backend directory. Install
Tesseract (`brew install tesseract` on macOS or `sudo apt-get install tesseract-ocr`
on Debian/Ubuntu) to enable OCR. Set `VEYRO_TESSERACT_CMD` only if its executable
is not on PATH. For vision and web research, configure the selected provider's
API key and `BRAVE_SEARCH_API_KEY` in the backend process environment.
`VISION_PROVIDER` selects `gemini` (the default) or `openai`. Set `GEMINI_API_KEY`
for Gemini vision; `GEMINI_VISION_MODEL` is optional and defaults to
`gemini-3.1-flash-lite`. Set `OPENAI_API_KEY` to use OpenAI; its optional
`OPENAI_VISION_MODEL` defaults to `gpt-6-luna`. If the selected provider has no
key, image analysis is reported unavailable and no visual identity fields are
added. Provider-reported per-observation confidence describes extraction
confidence only; it is not an authenticity probability.

## Developer UI

Start the API from `backend/` with `uv run uvicorn app.main:app --reload`.
In another terminal, run `npm install` and `npm run dev` from `frontend/`, then
open the Vite URL (normally http://localhost:5173). Set
`VITE_VEYRO_API_BASE_URL` when the API is hosted at another origin; local
development proxies `/v1` to `http://127.0.0.1:8000`. The API allows the two
localhost Vite origins by default; configure others with the comma-separated
`VEYRO_CORS_ORIGINS` environment variable.

Run frontend checks with `npm test` and `npm run build` from `frontend/`.
