from fastapi import FastAPI
from pydantic import BaseModel

from .providers import IndiaFootwearProvider
from .requirements import extract_requirements
from .research import research

app = FastAPI(title="Veyro API", version="0.1.0")

provider = IndiaFootwearProvider()


class ShoppingRequest(BaseModel):
    query: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "veyro", "market": "IN"}


@app.post("/v1/requirements")
def requirements(request: ShoppingRequest) -> dict[str, object]:
    parsed = extract_requirements(request.query)
    return {
        "query": request.query,
        "requirements": parsed.model_dump(),
    }


@app.post("/v1/research")
def research_endpoint(request: ShoppingRequest) -> dict[str, object]:
    parsed = extract_requirements(request.query)
    products = research(request.query, parsed, provider)
    return {
        "query": request.query,
        "market": "IN",
        "currency": "INR",
        "requirements": parsed.model_dump(),
        "products": [product.model_dump() for product in products],
        "provider": "india_footwear",
    }
