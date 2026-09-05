from backend.dataset import DatasetCatalog


def test_catalog_loads_expected_dataset() -> None:
    catalog = DatasetCatalog()
    assert len(catalog.images) == 1090
    assert len(catalog.crops) == 13722
    assert sum(image["crop_count"] == 0 for image in catalog.images) == 13


def test_catalog_does_not_expose_model_labels_or_scores() -> None:
    payload = DatasetCatalog().payload()
    serialized = str(payload)
    assert "rectanglelabels" not in serialized
    assert "score" not in serialized
    assert "present" not in serialized
    assert "absent" not in serialized

