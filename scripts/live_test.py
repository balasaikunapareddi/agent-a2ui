"""Live end-to-end test: runs the REAL agent (LiteLLM) through the flow.

Requires a provider API key in the environment (e.g. GEMINI_API_KEY for
the default gemini/gemini-3.5-flash-lite). Run via the portfolio harness:

  python3 ~/workspace/custom-connectors/custom.gemini/bin/run_live.py \
      ~/workspace/agent-a2ui .venv/bin/python scripts/live_test.py

If the free-tier daily quota is exhausted you will see a 429 — that is
recorded honestly; do not retry-loop.
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_a2ui.agent import A2UIBookingAgent  # noqa: E402
from agent_a2ui.binding import contains_sensitive_values  # noqa: E402
from agent_a2ui.cli import DEMO_PATIENT  # noqa: E402


def main() -> int:
    today = date.today()
    agent = A2UIBookingAgent(patient=DEMO_PATIENT, today=today)

    print("== turn 1: patient asks to book ==")
    turn = agent.handle_user_text("Book me a checkup next week")
    print("text:", turn.text)
    print("surfaces:", [s["surface_id"] for s in turn.surfaces])
    types = [c["component"] for s in turn.surfaces for c in s["components"]]
    print("components:", types)
    if "SlotPicker" not in types:
        print("FAIL: expected a SlotPicker surface")
        return 1

    slot = agent.calendar.check_availability(today, today + timedelta(days=7))[0]
    print(f"\n== turn 2: patient picks {slot.label} ==")
    turn = agent.handle_action(
        "slotSelected", {"slot_id": slot.slot_id, "slot_label": slot.label}
    )
    types = [c["component"] for s in turn.surfaces for c in s["components"]]
    print("components:", types)

    print("\n== turn 3: intake submitted ==")
    turn = agent.handle_action(
        "intakeSubmitted",
        {
            "slot_id": slot.slot_id,
            "slot_label": slot.label,
            "reason": "Annual checkup",
            "contact_method": "Text message",
        },
    )
    types = [c["component"] for s in turn.surfaces for c in s["components"]]
    print("components:", types)
    print("bookings before confirm:", len(agent.calendar.bookings()))

    print("\n== turn 4: patient confirms ==")
    turn = agent.handle_action(
        "bookingConfirmed",
        {
            "slot_id": slot.slot_id,
            "reason": "Annual checkup",
            "contact_method": "Text message",
        },
    )
    types = [c["component"] for s in turn.surfaces for c in s["components"]]
    print("components:", types)
    bookings = agent.calendar.bookings()
    print("bookings after confirm:", len(bookings))

    leaked = contains_sensitive_values(agent.emitted_messages, DEMO_PATIENT)
    print("\nPII in model-emitted messages:", leaked or "none")
    print("\nlast A2UI message:")
    if agent.emitted_messages:
        print(json.dumps(agent.emitted_messages[-1], indent=2)[:1500])

    ok = len(bookings) == 1 and not leaked
    print("\nLIVE TEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
