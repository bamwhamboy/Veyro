from app.requirements import extract_requirements


def test_extracts_shoe_requirements() -> None:
    result = extract_requirements(
        "I need comfortable walking shoes under ₹10,000 for a wide foot. "
        "I prefer ASICS or Skechers."
    )

    assert result.category == "shoes"
    assert result.budget_max_inr == 10000
    assert result.width == "wide"
    assert result.brands == ["asics", "skechers"]
    assert "walking" in result.use_case
    assert "comfortable" in result.preferences
