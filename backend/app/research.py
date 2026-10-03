from .domain import ShoppingRequirements
from .products import Product, ProductProvider


def filter_products(
    products: list[Product], requirements: ShoppingRequirements
) -> list[Product]:
    results = products

    if requirements.budget_max_inr is not None:
        results = [
            p for p in results
            if p.price_inr is not None and p.price_inr <= requirements.budget_max_inr
        ]

    if requirements.brands:
        wanted = {brand.lower() for brand in requirements.brands}
        results = [p for p in results if p.brand.lower() in wanted]

    if requirements.width:
        results = [p for p in results if p.width == requirements.width]

    if requirements.use_case:
        results = [
            p for p in results
            if any(use_case in p.use_case for use_case in requirements.use_case)
        ]

    return results


def research(
    query: str,
    requirements: ShoppingRequirements,
    provider: ProductProvider,
) -> list[Product]:
    candidates = provider.search(query)
    return filter_products(candidates, requirements)
