"""Data binding: JSON Pointer resolution + PII stays server-side."""

from agent_a2ui.binding import (
    attach_patient_data,
    contains_sensitive_values,
    resolve_pointer,
    resolve_value,
    set_pointer,
)

PATIENT = {"name": "Priya Sharma", "phone": "+1-555-014-2200", "dob": "1990-04-12"}


def test_resolve_pointer_nested():
    data = {"patient": {"name": "Priya"}, "slots": [{"slot_id": "s1"}]}
    assert resolve_pointer(data, "/patient/name") == "Priya"
    assert resolve_pointer(data, "/slots/0/slot_id") == "s1"
    assert resolve_pointer(data, "/missing/path") is None
    assert resolve_pointer(data, "/") == data


def test_set_pointer_creates_and_deletes():
    data: dict = {}
    set_pointer(data, "/patient/name", "Priya")
    assert data == {"patient": {"name": "Priya"}}
    set_pointer(data, "/patient/name", None)
    assert data == {"patient": {}}


def test_resolve_value_literal_and_binding():
    data = {"patient": {"name": "Priya"}}
    assert resolve_value("literal", data) == "literal"
    assert resolve_value({"@path": "/patient/name"}, data) == "Priya"
    assert resolve_value({"@path": "/nope"}, data) is None


def test_attach_patient_data_does_not_mutate_input():
    model_data = {"slots": []}
    merged = attach_patient_data(model_data, PATIENT)
    assert "patient" not in model_data
    assert merged["patient"] == PATIENT


def test_model_visible_payload_has_paths_not_values():
    """The core privacy proof: what the model produced contains only
    /patient/* paths — never the actual name, phone or DOB."""
    model_surface = {
        "components": [
            {
                "id": "root",
                "component": "ApprovalCard",
                "title": "Review",
                "slot_label": "Mon 09:00",
                "reason": "Checkup",
                "contact_method": "Email",
                "patient_name": {"@path": "/patient/name"},
            }
        ],
        "dataModel": {"slots": [{"slot_id": "s1", "label": "Mon 09:00"}]},
    }
    assert contains_sensitive_values(model_surface, PATIENT) == []
    # ...while the render-time data model DOES carry the values.
    render_data = attach_patient_data(model_surface["dataModel"], PATIENT)
    assert contains_sensitive_values(render_data, PATIENT) == list(PATIENT.values())
