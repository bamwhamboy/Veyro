# Veyro Agent Instructions

## Goal

Build Veyro as an AI-powered product authenticity verification platform,
starting with footwear in India.

## Engineering principles

- Keep submissions, product identification, evidence collection, comparison,
  assessment, and reporting as separate steps.
- Every assessment claim and conclusion must cite evidence IDs included in the
  report; evidence must cite a provenance source.
- Keep web search, OCR, vision, and brand/catalogue integrations behind
  replaceable provider interfaces.
- Store submitted metadata and uploaded photos durably; do not keep request
  uploads only in process memory.
- Treat user listing details and provider output as unverified until assessed.
- Do not introduce shopping recommendations or fabricated/demo evidence into
  production verification.
- Keep Sprint 0 as a single pipeline; do not add multi-agent/deep-agent
  architecture.

## Sprint 1 scope

India and footwear only. Accept real listing/photo submissions, extract
visible fields with OCR, report photo quality, and preserve evidence links.
Keep production vision, web research, and brand catalogue services behind the
same replaceable interfaces.

The current implementation also includes Sprint 2 web identification, Sprint
3 evidence comparison and persistence, Sprint 4 explainable assessments, and a
Sprint 5 local developer UI. Gemini and OpenAI vision providers are selectable
through configuration and share one provider interface.
