# Veyro Agent Instructions

## Goal

Build Veyro as a modular AI shopping-research platform, starting with shoes.

## Engineering principles

- Prefer small, testable components.
- Keep product research/provider integrations behind clear interfaces.
- Separate user-requirement extraction from product retrieval, normalisation, ranking and explanation.
- Never hard-code retailer-specific logic into the core orchestrator.
- Treat price, availability and product attributes as time-sensitive data.
- Make model/provider choices configurable.
- Add tests for core business logic before adding complexity.

## v0.1 scope

Implement a thin vertical slice that can accept a shopping request, extract structured requirements, run product research through a provider interface, filter candidates, and return an explainable shortlist.

Do not build multi-agent/deep-agent complexity until the single-agent flow is working end to end.
