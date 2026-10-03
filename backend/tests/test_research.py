from app.domain import ShoppingRequirements
from app.products import Product
from app.research import filter_products


def test_filters_by_hard_constraints() -> None:
    products = [
        Product(
            name="Wide Walker",
            brand="Skechers",
            price_inr=7999,
            source="test",
            use_case=["walking"],
            width="wide",
        ),
        Product(
            name="Too Expensive",
            brand="Skechers",
            price_inr=12999,
            source="test",
            use_case=["walking"],
            width="wide",
        ),
        Product(
            name="Wrong Width",
            brand="ASICS",
            price_inr=8999,
            source="test",
            use_case=["walking"],
            width="standard",
        ),
    ]

    requirements = ShoppingRequirements(
        budget_max_inr=10000,
        brands=["Skechers"],
        width="wide",
        use_case=["walking"],
    )

    result = filter_products(products, requirements)

    assert [p.name for p in result] == ["Wide Walker"]
