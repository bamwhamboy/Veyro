from .products import Product, ProductProvider


class IndiaFootwearProvider(ProductProvider):
    """India-first provider. Live retailer adapters will implement this interface."""

    market = "IN"

    _products = [
        Product(
            name="Example Daily Walker",
            brand="Skechers",
            price_inr=7999,
            source="demo",
            market="IN",
            use_case=["walking", "daily wear"],
            width="wide",
            features=["comfortable", "cushioned", "lightweight"],
        ),
        Product(
            name="Example Running Shoe",
            brand="ASICS",
            price_inr=9499,
            source="demo",
            market="IN",
            use_case=["running", "walking"],
            width="standard",
            features=["cushioned", "breathable", "lightweight"],
        ),
        Product(
            name="Example Premium Walker",
            brand="Nike",
            price_inr=11999,
            source="demo",
            market="IN",
            use_case=["walking"],
            width="standard",
            features=["comfortable", "cushioned"],
        ),
    ]

    def search(self, query: str, *, limit: int = 20) -> list[Product]:
        return self._products[:limit]


# Future markets can add providers without changing the research layer:
# class USFootwearProvider(ProductProvider): ...
# class UKFootwearProvider(ProductProvider): ...
