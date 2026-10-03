import re

from .domain import ShoppingRequirements


BRANDS = ("nike", "puma", "asics", "crocs", "skechers", "adidas", "new balance")


def extract_requirements(query: str) -> ShoppingRequirements:
    text = query.lower()

    budget = None
    patterns = [
        r"(?:under|below|less than|within)\s*[₹rs.]*\s*([0-9,]+)\s*(?:k)?",
        r"[₹rs.]*\s*([0-9,]+)\s*(?:k)?\s*(?:max|maximum)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = int(match.group(1).replace(",", ""))
            if "k" in match.group(0):
                value *= 1000
            budget = value
            break

    use_case = []
    for phrase in ("walking", "running", "daily wear", "gym", "travel", "standing"):
        if phrase in text:
            use_case.append(phrase)

    brands = [brand for brand in BRANDS if brand in text]

    width = None
    if "wide foot" in text or "wide feet" in text or "wide fit" in text:
        width = "wide"
    elif "narrow foot" in text or "narrow fit" in text:
        width = "narrow"

    gender = None
    if "women" in text or "female" in text:
        gender = "women"
    elif "men" in text or "male" in text:
        gender = "men"

    preferences = []
    for phrase in ("comfortable", "cushioned", "lightweight", "breathable", "durable"):
        if phrase in text:
            preferences.append(phrase)

    return ShoppingRequirements(
        use_case=use_case,
        budget_max_inr=budget,
        brands=brands,
        width=width,
        gender=gender,
        preferences=preferences,
    )
