"""Server-side data binding.

A2UI separates UI structure from data: components reference values with
JSON Pointer bindings like {"@path": "/patient/name"} and the renderer
resolves them against the surface's data model at draw time.

The privacy property this example is built around: the LLM composes
components containing only *paths*. Sensitive values (patient name,
phone, date of birth) are injected into the data model by server code
(`attach_patient_data`) AFTER the model has emitted the surface, and
resolved by the renderer. The model never receives them — not in its
prompt, not in tool results, not in the surfaces it produced.
"""

from __future__ import annotations

import copy
from typing import Any

# Paths whose values are sensitive and must only ever be filled in
# server-side. The model may reference these paths but never sees values.
SENSITIVE_PATHS = ("/patient/name", "/patient/phone", "/patient/dob")


def resolve_pointer(data_model: dict[str, Any], pointer: str) -> Any:
    """Resolve a JSON Pointer (RFC 6901) against a nested dict/list.

    Returns None when the path does not exist.
    """
    if pointer in ("", "/"):
        return data_model
    node: Any = data_model
    for raw in pointer.lstrip("/").split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            if key not in node:
                return None
            node = node[key]
        elif isinstance(node, list):
            try:
                node = node[int(key)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return node


def set_pointer(data_model: dict[str, Any], pointer: str, value: Any) -> None:
    """Set (or, when value is None, delete) the value at a JSON Pointer."""
    if pointer in ("", "/"):
        data_model.clear()
        if isinstance(value, dict):
            data_model.update(value)
        return
    parts = [p.replace("~1", "/").replace("~0", "~") for p in pointer.lstrip("/").split("/")]
    node: Any = data_model
    for key in parts[:-1]:
        if isinstance(node, dict):
            node = node.setdefault(key, {})
        elif isinstance(node, list):
            node = node[int(key)]
        else:  # pragma: no cover - defensive
            raise ValueError(f"cannot traverse through {type(node).__name__} at {pointer}")
    last = parts[-1]
    if isinstance(node, dict):
        if value is None:
            node.pop(last, None)
        else:
            node[last] = value
    elif isinstance(node, list):
        node[int(last)] = value


def is_binding(value: Any) -> bool:
    return isinstance(value, dict) and ("@path" in value or "@call" in value)


def resolve_value(value: Any, data_model: dict[str, Any]) -> Any:
    """Resolve one dynamic prop value against the data model.

    Literals pass through. {"@path": ...} resolves via JSON Pointer.
    {"@call": ...} is not executed by this renderer (function calls are
    handled through the /function endpoint instead) and resolves to None.
    """
    if isinstance(value, dict) and "@path" in value:
        return resolve_pointer(data_model, value["@path"])
    if isinstance(value, dict) and "@call" in value:
        return None
    return value


def attach_patient_data(
    data_model: dict[str, Any], patient: dict[str, str]
) -> dict[str, Any]:
    """Return a copy of the data model with the patient record attached.

    Called by server code only, at render time. The input data model is
    the one the model produced (paths only, no values); the output is
    what the renderer resolves against.
    """
    merged = copy.deepcopy(data_model)
    merged["patient"] = {
        "name": patient["name"],
        "phone": patient["phone"],
        "dob": patient["dob"],
    }
    return merged


def contains_sensitive_values(payload: Any, patient: dict[str, str]) -> list[str]:
    """Return which sensitive patient values appear anywhere in `payload`.

    Used by tests (and available as a runtime guard) to prove the
    model-visible payload contains data paths only, never PII values.
    """
    import json

    text = json.dumps(payload, default=str)
    return [v for v in patient.values() if v and v in text]
