"""The clinic component catalog — the ONLY UI the agent is allowed to emit.

This is the safety core of the example. The agent composes A2UI surfaces
from these seven registered components and nothing else. Every component
the model emits is validated against this catalog with the official A2UI
Python SDK (`a2ui-agent-sdk`); an unregistered component type or invalid
props are rejected before anything reaches the renderer.

Component models are pydantic models extending the SDK's `ComponentCommon`
(which carries `id`, `@catalogId`, `@accessibility`, `@metadata`). Dynamic
props accept either a literal or a data binding (`{"@path": ...}` /
`{"@call": ...}`), exactly as in the A2UI 1.0 spec.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from a2ui.core.catalog.catalog import Catalog
from a2ui.core.catalog.components import ModelComponentApi
from a2ui.core.schema.v1_0.common_types import (
    ComponentCommon,
    DataBinding,
    DynamicString,
    FunctionCall,
)
from a2ui.core.validation.payload_validator import (
    A2uiValidationError,
    PayloadValidator,
)

CATALOG_ID = "https://northside-clinic.example/a2ui/catalogs/clinic/catalog.json"
PROTOCOL_VERSION = "1.0"

# A value that is either bound to the data model or produced by a function.
BoundValue = DataBinding | FunctionCall


class Column(ComponentCommon):
    """Layout container: stacks its children vertically."""

    component: Literal["Column"] = "Column"
    children: list[str] = Field(default_factory=list)


class Text(ComponentCommon):
    """A line of text. `text` may be a literal or a data binding."""

    component: Literal["Text"] = "Text"
    text: DynamicString
    variant: Literal["title", "body", "caption"] | None = None


class SlotPicker(ComponentCommon):
    """Lets the patient pick one appointment slot.

    `options` binds to the slot list in the data model (e.g. /slots).
    When the patient picks, the renderer sends back an action named
    `action` with the chosen slot_id.
    """

    component: Literal["SlotPicker"] = "SlotPicker"
    title: DynamicString
    options: BoundValue
    action: str = "slotSelected"


class IntakeForm(ComponentCommon):
    """Collects visit details.

    Reason for visit and preferred contact method are entered by the
    patient. Name, phone and date of birth are rendered read-only from
    /patient/* bindings — the model never sees those values.
    """

    component: Literal["IntakeForm"] = "IntakeForm"
    title: DynamicString
    reason_label: str = "Reason for visit"
    contact_label: str = "Preferred contact method"
    contact_options: list[str] = Field(
        default_factory=lambda: ["Phone call", "Text message", "Email"]
    )
    action: str = "intakeSubmitted"


class ApprovalCard(ComponentCommon):
    """Final review. Nothing is booked until the patient confirms here."""

    component: Literal["ApprovalCard"] = "ApprovalCard"
    title: DynamicString
    slot_label: DynamicString
    reason: DynamicString
    contact_method: DynamicString
    patient_name: DynamicString
    confirm_action: str = "bookingConfirmed"
    cancel_action: str = "bookingCancelled"


class InfoCard(ComponentCommon):
    """A confirmation / information display."""

    component: Literal["InfoCard"] = "InfoCard"
    title: DynamicString
    body: DynamicString
    detail: DynamicString | None = None


class AvailabilityChart(ComponentCommon):
    """Open-slot counts per day, rendered as simple bars."""

    component: Literal["AvailabilityChart"] = "AvailabilityChart"
    title: DynamicString
    days: BoundValue


COMPONENT_MODELS = [
    Column,
    Text,
    SlotPicker,
    IntakeForm,
    ApprovalCard,
    InfoCard,
    AvailabilityChart,
]

COMPONENT_NAMES = [m.__name__ for m in COMPONENT_MODELS]


def build_catalog() -> Catalog:
    """Build the clinic catalog using the official A2UI SDK."""
    return Catalog(
        catalog_id=CATALOG_ID,
        protocol_version=PROTOCOL_VERSION,
        components=[ModelComponentApi(m) for m in COMPONENT_MODELS],
    )


class CatalogValidationError(ValueError):
    """Raised when a component fails catalog validation."""


class ClinicCatalog:
    """Catalog + validator pair used by the agent and the renderer."""

    def __init__(self) -> None:
        self.catalog = build_catalog()
        self._validator = PayloadValidator(self.catalog)

    def validate_component(self, component: dict[str, Any]) -> None:
        """Validate one component dict against the catalog.

        Raises CatalogValidationError with a human-readable message when
        the component type is not registered or its props are invalid.
        """
        try:
            self._validator.validate_component(component)
        except A2uiValidationError as exc:
            raise CatalogValidationError(str(exc)) from exc

    def validate_components(self, components: list[dict[str, Any]]) -> None:
        """Validate a flat component list (a whole surface)."""
        if not components:
            raise CatalogValidationError("surface has no components")
        ids = [c.get("id") for c in components]
        if "root" not in ids:
            raise CatalogValidationError(
                'surface must contain a component with id "root"'
            )
        if len(ids) != len(set(ids)):
            raise CatalogValidationError("component ids must be unique")
        for component in components:
            self.validate_component(component)
