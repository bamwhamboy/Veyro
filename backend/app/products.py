from pydantic import BaseModel, Field


class Product(BaseModel):
    name: str
    brand: str
    price_inr: int | None = None
    url: str | None = None
    source: str
    market: str = "IN"
    use_case: list[str] = Field(default_factory=list)
    width: str | None = None
    features: list[str] = Field(default_factory=list)


class ProductProvider:
    market: str = "IN"

    def search(self, query: str, *, limit: int = 20) -> list[Product]:
        raise NotImplementedError
