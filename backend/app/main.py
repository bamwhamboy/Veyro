from fastapi import FastAPI
from pydantic import BaseModel

from .requirements import extract_requirements

app = FastAPI(title="Veyro API", version="0.1.0")


class ShoppingRequest(BaseModel):
    query: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "veyro"}


@app.post("/v1/requirements")
def requirements(request: ShoppingRequest) -> dict[str, object]:
    parsed = extract_requirements(request.query)
    return {
        "query": request.query,
        "requirements": parsed.model_dump(),
    }


@app.post("/v1/research")
def research(request: ShoppingRequest) -> dict[str, object]:
    parsed = extract_requirements(request.query)
    return {
        "query": request.query,
        "requirements": parsed.model_dump(),
        "status": "research_pending",
    }
