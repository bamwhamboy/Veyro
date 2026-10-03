from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Veyro API", version="0.1.0")


class ShoppingRequest(BaseModel):
    query: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "veyro"}


@app.post("/v1/research")
def research(request: ShoppingRequest) -> dict[str, object]:
    return {
        "query": request.query,
        "status": "not_implemented",
        "message": "Research pipeline will be added in the next slice.",
    }
