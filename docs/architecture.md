# Veyro Architecture

## v0.1

Veyro starts with one end-to-end research pipeline rather than multiple autonomous agents.

### Core components

1. Requirement extractor
   - Converts free-form intent into structured constraints.
2. Research orchestrator
   - Decides which research tools/providers to invoke.
3. Product providers
   - Search brand/retailer catalogues and web sources.
4. Product normaliser
   - Converts heterogeneous results into a common product model.
5. Constraint filter
   - Removes products that violate hard constraints.
6. Recommendation layer
   - Produces a transparent shortlist with reasons and trade-offs.

### Evolution path

Once the single pipeline works, specialist agents can be introduced around bounded tasks such as retailer research, review analysis, price checking and fit/feature analysis. An orchestrator can then delegate only where the added complexity is justified.
