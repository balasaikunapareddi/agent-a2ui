"""Server-side HTML renderer for A2UI surfaces.

There is no official Python renderer for A2UI (the official renderers
are React, Angular, Lit, Flutter, SwiftUI and Jetpack Compose), so this
module is a small, honest stand-in: it consumes the same A2UI messages
a real renderer would, maintains surface state (components by id +
data model), resolves {"@path": ...} bindings at draw time, and emits
server-rendered HTML. Interactions POST renderer actions back to the
agent, exactly like the protocol's renderer_to_agent channel.

Only catalog components can be rendered — anything else raises, which
is the renderer-side half of "the agent cannot invent UI".
"""

from __future__ import annotations

import html
from typing import Any

from .binding import resolve_value, set_pointer
from .messages import message_kind

RENDERABLE = {
    "Column",
    "Text",
    "SlotPicker",
    "IntakeForm",
    "ApprovalCard",
    "InfoCard",
    "AvailabilityChart",
}


class RenderError(ValueError):
    """Raised when a surface cannot be rendered."""


class SurfaceState:
    """Renderer-side state for one surface."""

    def __init__(self, surface_id: str) -> None:
        self.surface_id = surface_id
        self.components: dict[str, dict[str, Any]] = {}
        self.data_model: dict[str, Any] = {}

    def apply_components(self, components: list[dict[str, Any]]) -> None:
        for comp in components:
            self.components[comp["id"]] = comp

    def apply_data(self, path: str, value: Any) -> None:
        set_pointer(self.data_model, path, value)


class HtmlRenderer:
    """Applies A2UI messages and renders surfaces to HTML."""

    def __init__(self) -> None:
        self.surfaces: dict[str, SurfaceState] = {}

    def apply(self, message: dict[str, Any]) -> None:
        kind = message_kind(message)
        payload = message.get(kind, {})
        if kind == "createSurface":
            state = SurfaceState(payload["surfaceId"])
            if payload.get("dataModel") is not None:
                state.data_model = dict(payload["dataModel"])
            state.apply_components(payload.get("components") or [])
            self.surfaces[state.surface_id] = state
        elif kind == "updateComponents":
            state = self._require(payload["surfaceId"])
            state.apply_components(payload.get("components") or [])
        elif kind == "updateDataModel":
            state = self._require(payload["surfaceId"])
            state.apply_data(payload.get("path", "/"), payload.get("value"))
        elif kind == "deleteSurface":
            self.surfaces.pop(payload["surfaceId"], None)
        else:
            raise RenderError(f"unsupported message kind: {kind}")

    def render_surface(self, surface_id: str) -> str:
        state = self._require(surface_id)
        if "root" not in state.components:
            raise RenderError(f"surface {surface_id} has no root component")
        return self._render_component(state, "root")

    def render_all(self) -> str:
        return "\n".join(self.render_surface(sid) for sid in self.surfaces)

    # -- internals ------------------------------------------------------------

    def _require(self, surface_id: str) -> SurfaceState:
        state = self.surfaces.get(surface_id)
        if state is None:
            raise RenderError(f"unknown surface: {surface_id}")
        return state

    def _render_component(self, state: SurfaceState, comp_id: str) -> str:
        comp = state.components.get(comp_id)
        if comp is None:
            raise RenderError(f"missing component: {comp_id}")
        kind = comp.get("component")
        if kind not in RENDERABLE:
            raise RenderError(f"component not in renderer catalog: {kind}")
        handler = getattr(self, f"_render_{kind.lower()}")
        return handler(state, comp)

    def _val(self, state: SurfaceState, comp: dict[str, Any], prop: str) -> Any:
        return resolve_value(comp.get(prop), state.data_model)

    def _text(self, state: SurfaceState, comp: dict[str, Any], prop: str) -> str:
        value = self._val(state, comp, prop)
        return html.escape("" if value is None else str(value))

    def _render_column(self, state: SurfaceState, comp: dict[str, Any]) -> str:
        children = comp.get("children") or []
        inner = "\n".join(self._render_component(state, c) for c in children)
        return f'<div class="a2ui-column">{inner}</div>'

    def _render_text(self, state: SurfaceState, comp: dict[str, Any]) -> str:
        variant = comp.get("variant") or "body"
        tag = "h3" if variant == "title" else "p"
        return f'<{tag} class="a2ui-text {variant}">{self._text(state, comp, "text")}</{tag}>'

    def _render_slotpicker(self, state: SurfaceState, comp: dict[str, Any]) -> str:
        options = self._val(state, comp, "options") or []
        action = html.escape(str(comp.get("action", "slotSelected")))
        items = []
        for opt in options:
            slot_id = html.escape(str(opt.get("slot_id", "")))
            label = html.escape(str(opt.get("label", "")))
            items.append(
                f'<label class="slot"><input type="radio" name="slot_id" '
                f'value="{slot_id}" required> {label}</label>'
            )
        return (
            f'<form class="a2ui-card" method="post" action="/action">'
            f"<h3>{self._text(state, comp, 'title')}</h3>"
            f'<input type="hidden" name="action" value="{action}">'
            + "".join(items)
            + '<button type="submit">Continue</button></form>'
        )

    def _render_intakeform(self, state: SurfaceState, comp: dict[str, Any]) -> str:
        action = html.escape(str(comp.get("action", "intakeSubmitted")))
        reason_label = html.escape(str(comp.get("reason_label", "Reason for visit")))
        contact_label = html.escape(
            str(comp.get("contact_label", "Preferred contact method"))
        )
        options = comp.get("contact_options") or []
        opts = "".join(
            f'<option value="{html.escape(str(o))}">{html.escape(str(o))}</option>'
            for o in options
        )
        # Read-only patient fields resolved from server-side bindings.
        name = html.escape(str(resolve_value({"@path": "/patient/name"}, state.data_model) or ""))
        phone = html.escape(str(resolve_value({"@path": "/patient/phone"}, state.data_model) or ""))
        dob = html.escape(str(resolve_value({"@path": "/patient/dob"}, state.data_model) or ""))
        return (
            f'<form class="a2ui-card" method="post" action="/action">'
            f"<h3>{self._text(state, comp, 'title')}</h3>"
            f'<input type="hidden" name="action" value="{action}">'
            f'<div class="readonly"><span>Name</span><strong>{name}</strong></div>'
            f'<div class="readonly"><span>Phone</span><strong>{phone}</strong></div>'
            f'<div class="readonly"><span>Date of birth</span><strong>{dob}</strong></div>'
            f'<label>{reason_label}<input type="text" name="reason" required></label>'
            f'<label>{contact_label}<select name="contact_method">{opts}</select></label>'
            f'<button type="submit">Review booking</button></form>'
        )

    def _render_approvalcard(self, state: SurfaceState, comp: dict[str, Any]) -> str:
        confirm = html.escape(str(comp.get("confirm_action", "bookingConfirmed")))
        cancel = html.escape(str(comp.get("cancel_action", "bookingCancelled")))
        return (
            f'<div class="a2ui-card approval">'
            f"<h3>{self._text(state, comp, 'title')}</h3>"
            f'<div class="row"><span>Patient</span><strong>{self._text(state, comp, "patient_name")}</strong></div>'
            f'<div class="row"><span>Appointment</span><strong>{self._text(state, comp, "slot_label")}</strong></div>'
            f'<div class="row"><span>Reason</span><strong>{self._text(state, comp, "reason")}</strong></div>'
            f'<div class="row"><span>Contact</span><strong>{self._text(state, comp, "contact_method")}</strong></div>'
            f'<form method="post" action="/action" class="actions">'
            f'<button type="submit" name="action" value="{confirm}">Confirm booking</button>'
            f'<button type="submit" name="action" value="{cancel}" class="secondary">Cancel</button>'
            f"</form></div>"
        )

    def _render_infocard(self, state: SurfaceState, comp: dict[str, Any]) -> str:
        detail = self._text(state, comp, "detail")
        detail_html = f'<p class="detail">{detail}</p>' if detail else ""
        return (
            f'<div class="a2ui-card info"><h3>{self._text(state, comp, "title")}</h3>'
            f"<p>{self._text(state, comp, 'body')}</p>{detail_html}</div>"
        )

    def _render_availabilitychart(self, state: SurfaceState, comp: dict[str, Any]) -> str:
        days = self._val(state, comp, "days") or []
        max_open = max((d.get("open", 0) for d in days), default=0) or 1
        bars = []
        for d in days:
            open_count = int(d.get("open", 0))
            width = round(100 * open_count / max_open)
            bars.append(
                f'<div class="bar-row"><span>{html.escape(str(d.get("day", "")))}</span>'
                f'<div class="bar" style="width:{width}%"></div>'
                f"<span>{open_count} open</span></div>"
            )
        return (
            f'<div class="a2ui-card chart"><h3>{self._text(state, comp, "title")}</h3>'
            + "".join(bars)
            + "</div>"
        )
