"""Source classification policy; trust is distinct from the source's kind."""
from __future__ import annotations

import os
from urllib.parse import urlparse


OFFICIAL_BRAND_DOMAINS = {
    "nike.com", "puma.com", "asics.com", "skechers.com", "adidas.com",
    "crocs.com", "newbalance.com",
    "in.puma.com", "asics.co.in", "skechers.in", "adidas.co.in",
    "crocs.in", "newbalance.co.in",
}
DEFAULT_ESTABLISHED_MARKETPLACES = {
    "amazon.in", "myntra.com", "ajio.com", "flipkart.com", "tatacliq.com",
}


def _domains_from_env(name: str, default: set[str]) -> set[str]:
    configured = os.environ.get(name)
    if configured is None:
        return set(default)
    return {item.strip().casefold().removeprefix("www.") for item in configured.split(",") if item.strip()}


def _matches_domain(host: str, domains: set[str]) -> bool:
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def classify_source(url: str | None) -> tuple[str, str]:
    """Return (source_type, trust_level); unknown web hosts stay low trust."""
    if not url:
        return "other_web", "low"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return "other_web", "low"
    host = parsed.hostname.casefold().removeprefix("www.")
    if _matches_domain(host, OFFICIAL_BRAND_DOMAINS):
        return "official_brand", "very_high"
    authorised = _domains_from_env("VEYRO_AUTHORISED_RETAILER_DOMAINS", set())
    if _matches_domain(host, authorised):
        return "authorised_retailer", "high"
    marketplaces = _domains_from_env(
        "VEYRO_ESTABLISHED_MARKETPLACE_DOMAINS", DEFAULT_ESTABLISHED_MARKETPLACES
    )
    if _matches_domain(host, marketplaces):
        return "established_marketplace", "medium"
    return "other_web", "low"
