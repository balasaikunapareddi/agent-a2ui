"""Full offline agent flow via the scripted DemoModel.

Covers: surface sequence, confirmation guardrail, PII never reaching
the model, and catalog rejection feeding errors back to the model.
"""

import json
from datetime import date, timedelta

from agent_a2ui.agent import A2UIBookingAgent, DemoModel
from agent_a2ui.binding import contains_sensitive_values

TODAY = date(2026, 11, 23)
PATIENT = {"name": "Priya Sharma", "phone": "+1-555-014-2200", "dob": "1990-04-12"}


def make_agent() -> A2UIBookingAgent:
    return A2UIBookingAgent(
        patient=PATIENT, model_fn=DemoModel(today=TODAY), today=TODAY
    )


def first_slot(agent: A2UIBookingAgent):
    return agent.calendar.check_availability(TODAY, TODAY + timedelta(days=7))[0]


def component_types(turn) -> list[str]:
    types = []
    for surface in turn.surfaces:
        types.extend(c["component"] for c in surface["components"])
    return types


def test_full_booking_flow():
    agent = make_agent()

    turn = agent.handle_user_text("Book me a checkup next week")
    assert "SlotPicker" in component_types(turn)
    assert "AvailabilityChart" in component_types(turn)

    slot = first_slot(agent)
    turn = agent.handle_action(
        "slotSelected", {"slot_id": slot.slot_id, "slot_label": slot.label}
    )
    assert component_types(turn) == ["IntakeForm"]

    turn = agent.handle_action(
        "intakeSubmitted",
        {
            "slot_id": slot.slot_id,
            "slot_label": slot.label,
            "reason": "Annual checkup",
            "contact_method": "Text message",
        },
    )
    assert component_types(turn) == ["ApprovalCard"]
    assert agent.calendar.bookings() == []  # nothing booked yet

    turn = agent.handle_action(
        "bookingConfirmed",
        {
            "slot_id": slot.slot_id,
            "reason": "Annual checkup",
            "contact_method": "Text message",
        },
    )
    assert component_types(turn) == ["InfoCard"]
    bookings = agent.calendar.bookings()
    assert len(bookings) == 1
    assert bookings[0].slot_id == slot.slot_id
    assert bookings[0].patient == PATIENT  # attached server-side


def test_booking_refused_without_confirmation():
    """The model cannot book on its own — confirmation is a UI action."""
    agent = make_agent()
    slot = first_slot(agent)
    result = agent._tool_book_appointment(
        {"slot_id": slot.slot_id, "reason": "x", "contact_method": "Email"}
    )
    assert "error" in result
    assert "not confirmed" in result["error"]
    assert agent.calendar.bookings() == []


def test_cancel_books_nothing():
    agent = make_agent()
    agent.handle_user_text("Book me a checkup")
    slot = first_slot(agent)
    agent.handle_action("slotSelected", {"slot_id": slot.slot_id})
    agent.handle_action(
        "intakeSubmitted",
        {"slot_id": slot.slot_id, "reason": "x", "contact_method": "Email"},
    )
    turn = agent.handle_action("bookingCancelled", {})
    assert component_types(turn) == ["InfoCard"]
    assert agent.calendar.bookings() == []


def test_pii_never_reaches_model():
    """Everything the model saw or produced must be free of PII values."""
    agent = make_agent()
    slot = first_slot(agent)
    agent.handle_user_text("Book me a checkup next week")
    agent.handle_action(
        "slotSelected", {"slot_id": slot.slot_id, "slot_label": slot.label}
    )
    agent.handle_action(
        "intakeSubmitted",
        {
            "slot_id": slot.slot_id,
            "slot_label": slot.label,
            "reason": "Annual checkup",
            "contact_method": "Text message",
        },
    )
    agent.handle_action(
        "bookingConfirmed",
        {
            "slot_id": slot.slot_id,
            "reason": "Annual checkup",
            "contact_method": "Text message",
        },
    )

    # 1) All A2UI messages the model emitted: paths only.
    assert contains_sensitive_values(agent.emitted_messages, PATIENT) == []
    # 2) The full conversation history the model ran under.
    assert contains_sensitive_values(agent._history, PATIENT) == []
    # 3) But the paths ARE there (binding is actually used).
    emitted = json.dumps(agent.emitted_messages)
    assert "/patient/name" in emitted


def test_invalid_surface_rejected_with_error_to_model():
    """A surface with an unregistered component never reaches the renderer;
    the model gets the validation error back instead."""
    agent = make_agent()
    from agent_a2ui.agent import TurnResult

    result = TurnResult()
    out = agent._tool_emit_surface(
        {
            "surface_id": "bad",
            "components": [{"id": "root", "component": "EvilWidget"}],
            "data_model": {},
        },
        result,
    )
    assert "error" in out
    assert "catalog validation failed" in out["error"]
    assert result.surfaces == []
    assert agent.emitted_messages == []


def test_booked_slot_disappears_from_availability():
    agent = make_agent()
    slot = first_slot(agent)
    agent.handle_user_text("Book me a checkup")
    agent.handle_action("slotSelected", {"slot_id": slot.slot_id})
    agent.handle_action(
        "intakeSubmitted",
        {"slot_id": slot.slot_id, "reason": "x", "contact_method": "Email"},
    )
    agent.handle_action(
        "bookingConfirmed",
        {"slot_id": slot.slot_id, "reason": "x", "contact_method": "Email"},
    )
    remaining = agent.calendar.check_availability(TODAY, TODAY + timedelta(days=7))
    assert slot.slot_id not in [s.slot_id for s in remaining]
