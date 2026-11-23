"""A2UI 1.0 message builders and envelope validation.

Messages follow the official v1.0 wire format (see
https://a2ui.org/specification/v1.0-a2ui/): every message is a JSON
object with "version": "1.0" and exactly one message key —
createSurface, updateComponents, updateDataModel, deleteSurface,
callRendererFunction or agentFunctionResponse.

Envelope validation uses the official SDK's pydantic models
(`a2ui.core.schema.v1_0.agent_to_renderer.AgentToRendererMessage`), so a
malformed message is rejected by the same code Google ships.
"""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter, ValidationError

from a2ui.core.schema.v1_0.agent_to_renderer import AgentToRendererMessage

from .catalog import CATALOG_ID

_ENVELOPE_ADAPTER = TypeAdapter(AgentToRendererMessage)


class MessageValidationError(ValueError):
    """Raised when a message fails A2UI envelope validation."""


def validate_message(message: dict[str, Any]) -> None:
    """Validate one agent-to-renderer message against the v1.0 schema."""
    try:
        _ENVELOPE_ADAPTER.validate_python(message)
    except ValidationError as exc:
        raise MessageValidationError(str(exc)) from exc


def create_surface(
    surface_id: str,
    components: list[dict[str, Any]],
    data_model: dict[str, Any] | None = None,
    *,
    catalog_id: str = CATALOG_ID,
    send_data_model: bool = True,
) -> dict[str, Any]:
    """Build a single-message createSurface (components + data inline)."""
    payload: dict[str, Any] = {
        "surfaceId": surface_id,
        "catalogId": catalog_id,
        "sendDataModel": send_data_model,
        "components": components,
    }
    if data_model is not None:
        payload["dataModel"] = data_model
    return {"version": "1.0", "createSurface": payload}


def update_components(
    surface_id: str, components: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "version": "1.0",
        "updateComponents": {"surfaceId": surface_id, "components": components},
    }


def update_data_model(
    surface_id: str, path: str, value: Any
) -> dict[str, Any]:
    return {
        "version": "1.0",
        "updateDataModel": {"surfaceId": surface_id, "path": path, "value": value},
    }


def delete_surface(surface_id: str) -> dict[str, Any]:
    return {"version": "1.0", "deleteSurface": {"surfaceId": surface_id}}


def agent_function_response(
    function_call_id: str,
    *,
    value: Any = None,
    error: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Response to a renderer-initiated callAgentFunction (1.0 RPC)."""
    payload: dict[str, Any] = {"functionCallId": function_call_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["value"] = value
    return {"version": "1.0", "agentFunctionResponse": payload}


def message_kind(message: dict[str, Any]) -> str:
    """Return the message-type key of an envelope message."""
    for key in message:
        if key != "version":
            return key
    return "unknown"
