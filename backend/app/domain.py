from pydantic import BaseModel, Field
from typing import Literal


class ShoppingRequirements(BaseModel):
    category: str = "shoes"
    use_case: list[str] = Field(default_factory=list)
    budget_max_inr: int | None = None
    brands: list[str] = Field(default_factory=list)
    width: Literal["wide", "standard", "narrow"] | None = None
    gender: Literal["men", "women", "unisex"] | None = None
    preferences: list[str] = Field(default_factory=list)
