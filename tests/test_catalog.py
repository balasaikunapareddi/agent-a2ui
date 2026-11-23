"""Catalog validation: the agent cannot invent UI."""

import pytest

from agent_a2ui.catalog import CatalogValidationError, ClinicCatalog


@pytest.fixture(scope="module")
def catalog() -> ClinicCatalog:
    return ClinicCatalog()


def test_registered_components_accepted(catalog):
    catalog.validate_component(
        {"id": "root", "component": "Text", "text": "Hello"}
    )
    catalog.validate_component(
        {
            "id": "root",
            "component": "SlotPicker",
            "title": "Pick a time",
            "options": {"@path": "/slots"},
        }
    )
    catalog.validate_component(
        {
            "id": "root",
            "component": "ApprovalCard",
            "title": "Review",
            "slot_label": "Mon 09:00",
            "reason": "Checkup",
            "contact_method": "Email",
            "patient_name": {"@path": "/patient/name"},
        }
    )


def test_unregistered_component_rejected(catalog):
    with pytest.raises(CatalogValidationError, match="Unrecognized component"):
        catalog.validate_component(
            {"id": "root", "component": "EvilWidget", "title": "x"}
        )


def test_basic_catalog_component_not_registered_here(catalog):
    # Button exists in Google's basic catalog but NOT in this clinic
    # catalog — the agent may only use what this app registered.
    with pytest.raises(CatalogValidationError):
        catalog.validate_component(
            {"id": "root", "component": "Button", "child": "x"}
        )


def test_invalid_prop_type_rejected(catalog):
    with pytest.raises(CatalogValidationError):
        catalog.validate_component(
            {"id": "root", "component": "Text", "text": 42}
        )


def test_unknown_prop_rejected(catalog):
    with pytest.raises(CatalogValidationError):
        catalog.validate_component(
            {"id": "root", "component": "Text", "text": "hi", "onclick": "evil()"}
        )


def test_missing_required_prop_rejected(catalog):
    with pytest.raises(CatalogValidationError):
        catalog.validate_component(
            {"id": "root", "component": "SlotPicker", "title": "Pick"}
            # options is required
        )


def test_surface_requires_root(catalog):
    with pytest.raises(CatalogValidationError, match="root"):
        catalog.validate_components(
            [{"id": "a", "component": "Text", "text": "hi"}]
        )


def test_surface_rejects_duplicate_ids(catalog):
    with pytest.raises(CatalogValidationError, match="unique"):
        catalog.validate_components(
            [
                {"id": "root", "component": "Text", "text": "a"},
                {"id": "root", "component": "Text", "text": "b"},
            ]
        )


def test_full_surface_accepted(catalog):
    catalog.validate_components(
        [
            {"id": "root", "component": "Column", "children": ["t", "p"]},
            {"id": "t", "component": "Text", "text": "Book", "variant": "title"},
            {
                "id": "p",
                "component": "SlotPicker",
                "title": "Pick",
                "options": {"@path": "/slots"},
                "action": "slotSelected",
            },
        ]
    )
