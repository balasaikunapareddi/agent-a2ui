"""A2UIBookingAgent — the agent at the heart of this example.

A real agent loop: the model plans, calls typed tools
(check_availability / emit_surface / book_appointment), composes A2UI
surfaces from the clinic catalog, and reacts to renderer actions
(slotSelected, intakeSubmitted, bookingConfirmed, ...).

Safety properties enforced in code, not just in the prompt:

1. Catalog-constrained UI — every surface the model emits is validated
   against the clinic catalog with the official A2UI SDK. Invalid
   components are rejected and the error is handed back to the model.
2. PII never reaches the model — patient name/phone/DOB live server-side
   and are attached to the data model at render time (see binding.py).
   Tool results returned to the model contain no patient values.
3. No booking without confirmation — `book_appointment` refuses to run
   until the patient has confirmed on the ApprovalCard (a renderer
   action only the UI can send).

The live model is provider-agnostic via LiteLLM: set LLM_MODEL
(default "gemini/gemini-3.5-flash-lite"). Tests and the offline demo
inject a scripted DemoModel through the same loop.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable

from .binding import attach_patient_data
from .catalog import CatalogValidationError, ClinicCatalog
from .messages import create_surface, validate_message
from .prompts import BOOKING_AGENT_SYSTEM_PROMPT
from .tools import TOOL_DEFINITIONS, ClinicCalendar

DEFAULT_MODEL = "gemini/gemini-3.5-flash-lite"
MAX_TOOL_ROUNDS = 8

# A model callable takes (messages, tools) and returns an assistant
# message dict in OpenAI format: {"content": str|None, "tool_calls": [...]}.
ModelFn = Callable[[list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]]


def litellm_model(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
    """Live model call via LiteLLM. Model from LLM_MODEL env var."""
    import litellm

    # Providers differ in which sampling params they accept; drop the
    # ones a given model rejects instead of failing the whole call.
    litellm.drop_params = True
    model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)
    response = litellm.completion(
        model=model,
        messages=messages,
        tools=tools,
        tool_choice="auto",
        temperature=0.2,
    )
    message = response.choices[0].message
    tool_calls = []
    for tc in message.tool_calls or []:
        tool_calls.append(
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
        )
    return {"role": "assistant", "content": message.content, "tool_calls": tool_calls}


@dataclass
class TurnResult:
    """What one agent turn produced."""

    text: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)  # A2UI messages
    surfaces: list[dict[str, Any]] = field(default_factory=list)  # render-ready surfaces


class A2UIBookingAgent:
    """Clinic booking agent that answers with A2UI surfaces.

    >>> agent = A2UIBookingAgent(patient={...})          # live LiteLLM model
    >>> agent = A2UIBookingAgent(patient={...}, model_fn=DemoModel(...))  # offline
    """

    def __init__(
        self,
        patient: dict[str, str],
        *,
        calendar: ClinicCalendar | None = None,
        model_fn: ModelFn | None = None,
        today: date | None = None,
    ) -> None:
        # Server-side only. Never placed in model messages or tool results.
        self._patient = dict(patient)
        self.calendar = calendar or ClinicCalendar(today=today)
        self.catalog = ClinicCatalog()
        self._model_fn: ModelFn = model_fn or litellm_model
        self._today = today or date.today()

        # Conversation state (model-visible parts contain no PII).
        self._history: list[dict[str, Any]] = [
            {"role": "system", "content": BOOKING_AGENT_SYSTEM_PROMPT}
        ]
        self._confirmed = False  # set ONLY by a bookingConfirmed action
        self._surface_counter = 0
        # Every A2UI message ever emitted (model-visible form: paths only).
        self.emitted_messages: list[dict[str, Any]] = []

    # -- public API ---------------------------------------------------------

    def handle_user_text(self, text: str) -> TurnResult:
        """Run one turn from a patient message."""
        self._history.append({"role": "user", "content": text})
        return self._run_loop()

    def handle_action(
        self, action: str, context: dict[str, Any] | None = None
    ) -> TurnResult:
        """Run one turn from a renderer action (button tap, form submit)."""
        context = context or {}
        if action == "bookingConfirmed":
            # The one place confirmation can come from: the patient's tap
            # on the ApprovalCard. The model cannot set this itself.
            self._confirmed = True
        event = {"action": action, "context": context}
        self._history.append(
            {
                "role": "user",
                "content": f"[renderer action] {json.dumps(event)}",
            }
        )
        return self._run_loop()

    # -- agent loop -----------------------------------------------------------

    def _run_loop(self) -> TurnResult:
        result = TurnResult()
        for _ in range(MAX_TOOL_ROUNDS):
            assistant = self._model_fn(self._history, TOOL_DEFINITIONS)
            self._history.append(assistant)
            if assistant.get("content"):
                result.text = assistant["content"]
            tool_calls = assistant.get("tool_calls") or []
            if not tool_calls:
                break
            for call in tool_calls:
                tool_result = self._dispatch(call, result)
                self._history.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "name": call["function"]["name"],
                        "content": json.dumps(tool_result),
                    }
                )
        return result

    def _dispatch(self, call: dict[str, Any], result: TurnResult) -> dict[str, Any]:
        name = call["function"]["name"]
        raw_args = call["function"].get("arguments") or "{}"
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except json.JSONDecodeError:
            return {"error": f"arguments were not valid JSON: {raw_args!r}"}

        if name == "check_availability":
            return self._tool_check_availability(args)
        if name == "emit_surface":
            return self._tool_emit_surface(args, result)
        if name == "book_appointment":
            return self._tool_book_appointment(args)
        return {"error": f"unknown tool: {name}"}

    # -- tools ----------------------------------------------------------------

    def _tool_check_availability(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            start = date.fromisoformat(args.get("start_date") or self._today.isoformat())
            end = date.fromisoformat(
                args.get("end_date") or (self._today + timedelta(days=7)).isoformat()
            )
        except ValueError as exc:
            return {"error": f"bad date: {exc}"}
        slots = self.calendar.check_availability(start, end)
        return {
            "slots": [s.to_public() for s in slots],
            "availability_by_day": self.calendar.availability_by_day(start, end),
        }

    def _tool_emit_surface(
        self, args: dict[str, Any], result: TurnResult
    ) -> dict[str, Any]:
        components = args.get("components") or []
        data_model = args.get("data_model") or {}
        surface_id = args.get("surface_id") or self._next_surface_id()

        # 1) Catalog validation — the agent cannot invent UI.
        try:
            self.catalog.validate_components(components)
        except CatalogValidationError as exc:
            return {"error": f"catalog validation failed: {exc}"}

        # 2) Envelope validation with the official SDK schema.
        message = create_surface(surface_id, components, data_model)
        try:
            validate_message(message)
        except ValueError as exc:
            return {"error": f"A2UI message validation failed: {exc}"}

        self.emitted_messages.append(message)
        result.messages.append(message)
        # The renderer gets the data model WITH patient data attached
        # server-side. The model only ever produced paths.
        result.surfaces.append(
            {
                "surface_id": surface_id,
                "components": components,
                "data_model": attach_patient_data(data_model, self._patient),
            }
        )
        return {"ok": True, "surface_id": surface_id, "components": len(components)}

    def _tool_book_appointment(self, args: dict[str, Any]) -> dict[str, Any]:
        if not self._confirmed:
            return {
                "error": (
                    "booking refused: the patient has not confirmed on the "
                    "ApprovalCard yet. Show the ApprovalCard and wait for the "
                    "bookingConfirmed action."
                )
            }
        try:
            booking = self.calendar.book(
                slot_id=args["slot_id"],
                reason=args.get("reason", ""),
                contact_method=args.get("contact_method", ""),
                patient=self._patient,  # attached server-side
            )
        except (KeyError, ValueError) as exc:
            return {"error": f"booking failed: {exc}"}
        self._confirmed = False  # one confirmation = one booking
        slot = self.calendar.get_slot(booking.slot_id)
        return {
            "ok": True,
            "confirmation_code": booking.confirmation_code,
            "slot_label": slot.label if slot else booking.slot_id,
        }

    def _next_surface_id(self) -> str:
        self._surface_counter += 1
        return f"booking-{self._surface_counter}"


class DemoModel:
    """Scripted stand-in model for the offline demo and tests.

    Drives the exact same agent loop and tools as the live model, with
    deterministic tool calls. It reads tool results from the history
    (e.g. the slot list) the way a real model would.
    """

    def __init__(self, today: date | None = None) -> None:
        self._today = today or date.today()
        self._step = 0

    def __call__(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        last_user = self._last_user_content(messages)
        tool_results = self._tool_results(messages)

        # After a surface was emitted successfully: end the turn quietly.
        last = self._last_tool_result(messages)
        if last is not None and last[0] == "emit_surface" and last[1].get("ok"):
            return {"role": "assistant", "content": None, "tool_calls": []}

        # After a booking result: confirm with an InfoCard.
        if "book_appointment" in tool_results and "confirmation_code" in json.dumps(
            tool_results["book_appointment"]
        ):
            code = tool_results["book_appointment"]["confirmation_code"]
            label = tool_results["book_appointment"].get("slot_label", "")
            return self._emit(
                "confirm",
                [
                    {"id": "root", "component": "InfoCard",
                     "title": "You're booked",
                     "body": f"Confirmation {code} — {label}",
                     "detail": {"@path": "/patient/name"}},
                ],
                {},
                text="All set — see your confirmation below.",
            )

        # After availability: show the SlotPicker.
        if "check_availability" in tool_results and "emit_surface" not in tool_results:
            data = tool_results["check_availability"]
            return self._emit(
                "pick-slot",
                [
                    {"id": "root", "component": "Column",
                     "children": ["chart", "picker"]},
                    {"id": "chart", "component": "AvailabilityChart",
                     "title": "Open slots this week",
                     "days": {"@path": "/availability_by_day"}},
                    {"id": "picker", "component": "SlotPicker",
                     "title": "Pick a time that works for you",
                     "options": {"@path": "/slots"},
                     "action": "slotSelected"},
                ],
                {
                    "slots": data.get("slots", []),
                    "availability_by_day": data.get("availability_by_day", []),
                },
                text="Here are the open times — pick one.",
            )

        # Patient picked a slot -> intake form.
        if "slotSelected" in last_user:
            return self._emit(
                "intake",
                [
                    {"id": "root", "component": "IntakeForm",
                     "title": "A few details before we book",
                     "action": "intakeSubmitted"},
                ],
                {},
                text="Almost there — just a couple of details.",
            )

        # Intake submitted -> approval card.
        if "intakeSubmitted" in last_user:
            ctx = self._action_context(last_user)
            return self._emit(
                "approve",
                [
                    {"id": "root", "component": "ApprovalCard",
                     "title": "Review your booking",
                     "slot_label": ctx.get("slot_label", ""),
                     "reason": ctx.get("reason", ""),
                     "contact_method": ctx.get("contact_method", ""),
                     "patient_name": {"@path": "/patient/name"},
                     "confirm_action": "bookingConfirmed",
                     "cancel_action": "bookingCancelled"},
                ],
                {},
                text="Please review and confirm.",
            )

        # Patient confirmed -> book it.
        if "bookingConfirmed" in last_user:
            ctx = self._action_context(last_user)
            return self._tool_call(
                "book_appointment",
                {
                    "slot_id": ctx.get("slot_id", ""),
                    "reason": ctx.get("reason", ""),
                    "contact_method": ctx.get("contact_method", ""),
                },
            )

        if "bookingCancelled" in last_user:
            return self._emit(
                "cancelled",
                [
                    {"id": "root", "component": "InfoCard",
                     "title": "No problem",
                     "body": "Nothing was booked. Ask again any time."},
                ],
                {},
                text="Cancelled — nothing booked.",
            )

        # Default first move: check availability for the coming week.
        if "check_availability" not in tool_results:
            start = self._today
            end = self._today + timedelta(days=7)
            return self._tool_call(
                "check_availability",
                {
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "visit_type": "checkup",
                },
            )

        return {"role": "assistant", "content": "Done.", "tool_calls": []}

    # -- helpers --------------------------------------------------------------

    def _emit(
        self,
        surface_id: str,
        components: list[dict[str, Any]],
        data_model: dict[str, Any],
        *,
        text: str,
    ) -> dict[str, Any]:
        call = self._tool_call(
            "emit_surface",
            {
                "surface_id": surface_id,
                "components": components,
                "data_model": data_model,
            },
        )
        call["content"] = text
        return call

    def _tool_call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self._step += 1
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": f"demo-call-{self._step}",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                }
            ],
        }

    @staticmethod
    def _last_user_content(messages: list[dict[str, Any]]) -> str:
        for m in reversed(messages):
            if m.get("role") == "user":
                return m.get("content") or ""
        return ""

    @staticmethod
    def _tool_results(messages: list[dict[str, Any]]) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for m in messages:
            if m.get("role") == "tool":
                try:
                    results[m.get("name", "")] = json.loads(m.get("content") or "{}")
                except json.JSONDecodeError:
                    results[m.get("name", "")] = {}
        return results

    @staticmethod
    def _last_tool_result(
        messages: list[dict[str, Any]],
    ) -> tuple[str, dict[str, Any]] | None:
        """Most recent tool result from the CURRENT turn (after last user msg)."""
        for m in reversed(messages):
            if m.get("role") == "user":
                return None  # tool results before this belong to earlier turns
            if m.get("role") == "tool":
                try:
                    return m.get("name", ""), json.loads(m.get("content") or "{}")
                except json.JSONDecodeError:
                    return m.get("name", ""), {}
        return None

    @staticmethod
    def _action_context(last_user: str) -> dict[str, Any]:
        try:
            payload = json.loads(last_user.split("[renderer action]", 1)[1].strip())
            return payload.get("context", {})
        except (IndexError, json.JSONDecodeError):
            return {}
