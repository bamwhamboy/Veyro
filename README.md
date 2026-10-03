# Veyro

Veyro is an AI shopping research agent.

## Initial focus

The first vertical is footwear. Veyro will turn a natural-language shopping request into a structured requirement, research products across multiple brands/retailers, filter unsuitable options, and explain the resulting shortlist.

## v0.1 flow

User request -> requirement extraction -> product research -> normalisation -> filtering -> recommendation

The architecture is intentionally modular so additional product categories and specialist agents can be added later.

## Project structure

- `backend/` — API and agent orchestration
- `frontend/` — web UI
- `tests/` — automated tests
- `docs/` — product and architecture notes
