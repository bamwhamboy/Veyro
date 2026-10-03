from app.identity_extraction import extract_identity, merge_identity_candidates


def test_extracts_only_visible_labeled_fields_with_evidence_and_confidence() -> None:
    identity, evidence = extract_identity(
        "NIKE MODEL: CT1234 SKU: N123-01 Style Code: ST456 "
        "Size: US 9 Colour: Black/White UPC: 012345678901",
        confidence=0.93,
        source_id="photo-source",
    )

    assert identity.brand == "Nike"
    assert identity.model_number == "CT1234"
    assert identity.sku == "N123-01"
    assert identity.style_code == "ST456"
    assert identity.size == "US 9"
    assert identity.colorway == "Black/White"
    assert identity.other_identifiers == {"upc": "012345678901"}
    assert identity.confidence == 0.93
    assert set(identity.evidence_ids) == {item.evidence_id for item in evidence}
    assert all(item.source_id == "photo-source" for item in evidence)


def test_does_not_guess_unknown_identity_fields() -> None:
    identity, evidence = extract_identity(
        "Comfortable sports footwear", confidence=0.8, source_id="photo-source"
    )
    assert identity.brand is None
    assert identity.model_number is None
    assert identity.sku is None
    assert identity.size is None
    assert identity.confidence == 0.0
    assert evidence == []


def test_extracts_explicit_model_name_without_mislabeling_it_as_a_code() -> None:
    identity, _ = extract_identity(
        "Model Name: Air Zoom Pegasus 41 Size UK 9",
        confidence=0.88,
        source_id="photo-source",
    )
    assert identity.product_name == "Air Zoom Pegasus 41"
    assert identity.model_number is None
    assert identity.size == "UK 9"


def test_conflicting_values_across_photos_are_left_unset() -> None:
    first, first_evidence = extract_identity(
        "Model: ABC123", confidence=0.9, source_id="photo-1"
    )
    second, second_evidence = extract_identity(
        "Model: XYZ789", confidence=0.95, source_id="photo-2"
    )

    merged, conflicts = merge_identity_candidates(
        [first, second], first_evidence + second_evidence
    )

    assert merged.model_number is None
    assert "model_number" in conflicts
    assert merged.confidence == 0.0
