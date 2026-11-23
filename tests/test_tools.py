"""Clinic calendar: real availability logic, bookings consume slots."""

from datetime import date, timedelta

import pytest

from agent_a2ui.tools import ClinicCalendar

TODAY = date(2026, 11, 23)  # a Monday
PATIENT = {"name": "Priya Sharma", "phone": "+1-555-014-2200", "dob": "1990-04-12"}


@pytest.fixture()
def calendar() -> ClinicCalendar:
    return ClinicCalendar(today=TODAY)


def test_availability_returns_open_weekday_slots(calendar):
    slots = calendar.check_availability(TODAY, TODAY + timedelta(days=7))
    assert slots, "expected some open slots"
    assert all(s.day.weekday() < 5 for s in slots)  # no weekends
    assert all(not s.booked for s in slots)


def test_availability_is_deterministic(calendar):
    a = [s.slot_id for s in calendar.check_availability(TODAY, TODAY + timedelta(days=3))]
    b = [s.slot_id for s in calendar.check_availability(TODAY, TODAY + timedelta(days=3))]
    assert a == b


def test_booking_consumes_the_slot(calendar):
    first = calendar.check_availability(TODAY, TODAY + timedelta(days=7))[0]
    booking = calendar.book(first.slot_id, "Checkup", "Email", PATIENT)
    assert booking.confirmation_code.startswith("NCK-")
    remaining = calendar.check_availability(TODAY, TODAY + timedelta(days=7))
    assert first.slot_id not in [s.slot_id for s in remaining]


def test_double_booking_fails(calendar):
    first = calendar.check_availability(TODAY, TODAY + timedelta(days=7))[0]
    calendar.book(first.slot_id, "Checkup", "Email", PATIENT)
    with pytest.raises(ValueError, match="already booked"):
        calendar.book(first.slot_id, "Again", "Email", PATIENT)


def test_unknown_slot_fails(calendar):
    with pytest.raises(ValueError, match="unknown slot"):
        calendar.book("slot-nope", "Checkup", "Email", PATIENT)


def test_availability_by_day_counts_open_slots(calendar):
    by_day = calendar.availability_by_day(TODAY, TODAY + timedelta(days=7))
    assert by_day
    assert all(d["open"] > 0 for d in by_day)
    assert sum(d["open"] for d in by_day) == len(
        calendar.check_availability(TODAY, TODAY + timedelta(days=7), limit=1000)
    )


def test_public_slot_shape_has_no_patient_data(calendar):
    slot = calendar.check_availability(TODAY, TODAY + timedelta(days=7))[0]
    public = slot.to_public()
    assert set(public) == {"slot_id", "label", "doctor"}
