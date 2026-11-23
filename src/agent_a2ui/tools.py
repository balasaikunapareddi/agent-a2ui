"""Clinic tools: a mock calendar with real logic, plus typed tool schemas.

The calendar is deterministic (seeded) but behaves like a real one:
weekday clinic hours, some slots pre-booked, and bookings actually
consume slots — book a slot and it disappears from availability.

The patient identity is attached server-side at booking time. The
model-facing `book_appointment` tool takes only slot_id, reason and
contact method — all non-sensitive — so PII never transits the model.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

DOCTORS = ["Dr. Patel", "Dr. Nguyen", "Dr. Garcia"]
SLOT_TIMES = ["09:00", "09:30", "10:00", "10:30", "11:00", "13:00", "13:30", "14:00", "14:30", "15:00", "15:30", "16:00"]


@dataclass
class Slot:
    slot_id: str
    day: date
    time: str
    doctor: str
    booked: bool = False

    @property
    def label(self) -> str:
        return f"{self.day.strftime('%a %b %d')} · {self.time} · {self.doctor}"

    def to_public(self) -> dict[str, str]:
        """Model/renderer-visible shape. No patient data, ever."""
        return {"slot_id": self.slot_id, "label": self.label, "doctor": self.doctor}


@dataclass
class Booking:
    confirmation_code: str
    slot_id: str
    reason: str
    contact_method: str
    # Server-side only. Never returned to the model.
    patient: dict[str, str] = field(default_factory=dict)


class ClinicCalendar:
    """Deterministic clinic calendar with real availability logic."""

    def __init__(self, today: date | None = None, horizon_days: int = 14) -> None:
        self.today = today or date.today()
        self._slots: dict[str, Slot] = {}
        self._bookings: dict[str, Booking] = {}
        self._seed(horizon_days)

    def _seed(self, horizon_days: int) -> None:
        for offset in range(horizon_days):
            day = self.today + timedelta(days=offset)
            if day.weekday() >= 5:  # clinic closed on weekends
                continue
            for i, time in enumerate(SLOT_TIMES):
                doctor = DOCTORS[(day.toordinal() + i) % len(DOCTORS)]
                slot_id = f"slot-{day.isoformat()}-{time.replace(':', '')}-{i}"
                # Deterministic pre-booking: roughly every 3rd slot taken.
                pre_booked = (day.toordinal() * 7 + i * 3) % 5 in (0, 2)
                self._slots[slot_id] = Slot(
                    slot_id=slot_id, day=day, time=time, doctor=doctor, booked=pre_booked
                )

    def check_availability(
        self, start: date, end: date, limit: int = 12
    ) -> list[Slot]:
        """Open slots in [start, end], earliest first."""
        open_slots = [
            s
            for s in self._slots.values()
            if not s.booked and start <= s.day <= end
        ]
        open_slots.sort(key=lambda s: (s.day, s.time))
        return open_slots[:limit]

    def availability_by_day(self, start: date, end: date) -> list[dict[str, Any]]:
        counts: dict[date, int] = {}
        for s in self._slots.values():
            if start <= s.day <= end and not s.booked:
                counts[s.day] = counts.get(s.day, 0) + 1
        return [
            {"day": d.strftime("%a %m/%d"), "open": counts[d]}
            for d in sorted(counts)
        ]

    def get_slot(self, slot_id: str) -> Slot | None:
        return self._slots.get(slot_id)

    def book(
        self,
        slot_id: str,
        reason: str,
        contact_method: str,
        patient: dict[str, str],
    ) -> Booking:
        """Book a slot. Raises ValueError if unknown or already taken."""
        slot = self._slots.get(slot_id)
        if slot is None:
            raise ValueError(f"unknown slot: {slot_id}")
        if slot.booked:
            raise ValueError(f"slot already booked: {slot_id}")
        slot.booked = True
        code = "NCK-" + hashlib.sha256(slot_id.encode()).hexdigest()[:6].upper()
        booking = Booking(
            confirmation_code=code,
            slot_id=slot_id,
            reason=reason,
            contact_method=contact_method,
            patient=dict(patient),
        )
        self._bookings[code] = booking
        return booking

    def bookings(self) -> list[Booking]:
        return list(self._bookings.values())


# ---------------------------------------------------------------------------
# Typed tool definitions exposed to the model (OpenAI/LiteLLM function format)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": (
                "Check real open appointment slots in the clinic calendar "
                "between two dates (inclusive). Call this before showing a "
                "SlotPicker. Never invent slots."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "First day to search, ISO format YYYY-MM-DD",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "Last day to search, ISO format YYYY-MM-DD",
                    },
                    "visit_type": {
                        "type": "string",
                        "description": "Visit type, e.g. 'checkup', 'follow-up'",
                    },
                },
                "required": ["start_date", "end_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "emit_surface",
            "description": (
                "Send an A2UI surface to the patient. Components must come "
                "from the clinic catalog (Column, Text, SlotPicker, "
                "IntakeForm, ApprovalCard, InfoCard, AvailabilityChart) and "
                "one component must have id 'root'. The surface is validated "
                "against the catalog; invalid components are rejected and "
                "the error is returned so you can fix them."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "surface_id": {
                        "type": "string",
                        "description": "Unique id for this surface, e.g. 'booking-1'",
                    },
                    "components": {
                        "type": "array",
                        "description": "Flat list of A2UI component objects",
                        "items": {"type": "object"},
                    },
                    "data_model": {
                        "type": "object",
                        "description": (
                            "Data for bindings, e.g. {\"slots\": [...]}. "
                            "Never put patient name/phone/dob here — reference "
                            "/patient/* paths instead; the server fills them in."
                        ),
                    },
                },
                "required": ["surface_id", "components"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": (
                "Book the chosen slot. Only works after the patient has "
                "confirmed on the ApprovalCard. Returns a confirmation code."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slot_id": {"type": "string", "description": "The slot to book"},
                    "reason": {"type": "string", "description": "Reason for visit"},
                    "contact_method": {
                        "type": "string",
                        "description": "Preferred contact method",
                    },
                },
                "required": ["slot_id", "reason", "contact_method"],
            },
        },
    },
]
