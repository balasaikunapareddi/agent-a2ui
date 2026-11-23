"""A2UI envelope messages: builders + official SDK schema validation."""

import pytest

from agent_a2ui.messages import (
    MessageValidationError,
    agent_function_response,
    create_surface,
    delete_surface,
    message_kind,
    update_components,
    update_data_model,
    validate_message,
)

COMPONENTS = [
    {"id": "root", "component": "Column", "children": ["t"]},
    {"id": "t", "component": "Text", "text": {"@path": "/patient/name"}},
]


def test_create_surface_validates():
    msg = create_surface("s1", COMPONENTS, {"patient": {"name": "x"}})
    validate_message(msg)  # must not raise
    assert msg["version"] == "1.0"
    assert message_kind(msg) == "createSurface"


def test_update_messages_validate():
    validate_message(update_components("s1", COMPONENTS))
    validate_message(update_data_model("s1", "/slots", []))
    validate_message(delete_surface("s1"))


def test_agent_function_response_validates():
    validate_message(agent_function_response("call-1", value={"ok": True}))
    validate_message(
        agent_function_response(
            "call-1", error={"code": "INVALID_FUNCTION_CALL", "message": "nope"}
        )
    )


def test_two_message_keys_rejected():
    bad = {
        "version": "1.0",
        "createSurface": {"surfaceId": "s1"},
        "deleteSurface": {"surfaceId": "s1"},
    }
    with pytest.raises(MessageValidationError):
        validate_message(bad)


def test_missing_surface_id_rejected():
    bad = {"version": "1.0", "createSurface": {"components": COMPONENTS}}
    with pytest.raises(MessageValidationError):
        validate_message(bad)


def test_wrong_version_rejected():
    bad = {"version": "0.9", "deleteSurface": {"surfaceId": "s1"}}
    with pytest.raises(MessageValidationError):
        validate_message(bad)
