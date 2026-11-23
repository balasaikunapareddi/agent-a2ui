"""Command line interface.

  python -m agent_a2ui demo            # full offline flow, prints A2UI JSON
  python -m agent_a2ui serve           # web UI (live model via LiteLLM)
  python -m agent_a2ui serve --offline # web UI with the scripted demo model
"""

from __future__ import annotations

import argparse
import json
from datetime import date

from .agent import A2UIBookingAgent, DemoModel, TurnResult
from .renderer import HtmlRenderer

DEMO_PATIENT = {
    "name": "Priya Sharma",
    "phone": "+1-555-014-2200",
    "dob": "1990-04-12",
}


def _show(turn: TurnResult, renderer: HtmlRenderer, heading: str) -> None:
    print(f"\n=== {heading} ===")
    if turn.text:
        print(f"agent says: {turn.text}")
    for message in turn.messages:
        print("A2UI message:")
        print(json.dumps(message, indent=2))
        renderer.apply(message)
    for surface in turn.surfaces:
        # Re-apply with the server-side data model (patient attached) so
        # the rendered HTML shows resolved bindings.
        state = renderer.surfaces[surface["surface_id"]]
        state.data_model = surface["data_model"]
        print(f"--- rendered HTML for surface '{surface['surface_id']}' ---")
        print(renderer.render_surface(surface["surface_id"]))


def run_demo() -> int:
    """Simulate the full booking flow offline with the scripted model."""
    today = date.today()
    agent = A2UIBookingAgent(
        patient=DEMO_PATIENT, model_fn=DemoModel(today=today), today=today
    )
    renderer = HtmlRenderer()

    turn = agent.handle_user_text("Book me a checkup next week")
    _show(turn, renderer, "1. Patient asks to book -> SlotPicker surface")

    slots = agent.calendar.check_availability(today, today)
    first = agent.calendar.check_availability(
        today, today.fromordinal(today.toordinal() + 7)
    )[0]
    turn = agent.handle_action(
        "slotSelected", {"slot_id": first.slot_id, "slot_label": first.label}
    )
    _show(turn, renderer, "2. Patient picks a slot -> IntakeForm surface")

    turn = agent.handle_action(
        "intakeSubmitted",
        {
            "slot_id": first.slot_id,
            "slot_label": first.label,
            "reason": "Annual checkup",
            "contact_method": "Text message",
        },
    )
    _show(turn, renderer, "3. Intake submitted -> ApprovalCard surface")

    turn = agent.handle_action(
        "bookingConfirmed",
        {
            "slot_id": first.slot_id,
            "reason": "Annual checkup",
            "contact_method": "Text message",
        },
    )
    _show(turn, renderer, "4. Patient confirms -> booking + InfoCard")

    bookings = agent.calendar.bookings()
    print(f"\nBookings in calendar: {len(bookings)}")
    for b in bookings:
        print(f"  {b.confirmation_code} slot={b.slot_id} reason={b.reason!r}")
    print("\nNote: the A2UI messages above contain /patient/* paths only.")
    print("The patient name/phone/DOB appear only in the rendered HTML,")
    print("resolved server-side at draw time. The model never saw them.")
    return 0


def run_serve(offline: bool, host: str, port: int) -> int:
    import uvicorn

    from .web import create_app

    app = create_app(offline=offline)
    uvicorn.run(app, host=host, port=port)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-a2ui")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("demo", help="run the full offline booking flow")

    serve = sub.add_parser("serve", help="run the web UI")
    serve.add_argument("--offline", action="store_true",
                       help="use the scripted demo model (no API key needed)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    if args.command == "demo":
        return run_demo()
    if args.command == "serve":
        return run_serve(args.offline, args.host, args.port)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
