"""HTML renderer: bindings resolve at draw time; unknown UI rejected."""

import pytest

from agent_a2ui.messages import create_surface, update_data_model
from agent_a2ui.renderer import HtmlRenderer, RenderError

PATIENT_DATA = {"patient": {"name": "Priya Sharma", "phone": "+1-555-014-2200", "dob": "1990-04-12"}}


def test_intake_form_renders_patient_from_bindings():
    renderer = HtmlRenderer()
    renderer.apply(
        create_surface(
            "intake",
            [{"id": "root", "component": "IntakeForm", "title": "Details"}],
            PATIENT_DATA,
        )
    )
    html_out = renderer.render_surface("intake")
    assert "Priya Sharma" in html_out
    assert "+1-555-014-2200" in html_out
    assert "1990-04-12" in html_out
    assert 'name="reason"' in html_out
    assert 'action="/action"' in html_out


def test_slot_picker_renders_options_from_data_model():
    renderer = HtmlRenderer()
    renderer.apply(
        create_surface(
            "pick",
            [
                {
                    "id": "root",
                    "component": "SlotPicker",
                    "title": "Pick",
                    "options": {"@path": "/slots"},
                }
            ],
            {"slots": [{"slot_id": "s1", "label": "Mon 09:00 · Dr. Patel"}]},
        )
    )
    html_out = renderer.render_surface("pick")
    assert 'value="s1"' in html_out
    assert "Mon 09:00" in html_out


def test_update_data_model_refreshes_bindings():
    renderer = HtmlRenderer()
    renderer.apply(
        create_surface(
            "pick",
            [
                {
                    "id": "root",
                    "component": "SlotPicker",
                    "title": "Pick",
                    "options": {"@path": "/slots"},
                }
            ],
            {"slots": []},
        )
    )
    renderer.apply(
        update_data_model(
            "pick", "/slots", [{"slot_id": "s9", "label": "Tue 10:00"}]
        )
    )
    assert 'value="s9"' in renderer.render_surface("pick")


def test_approval_card_renders_confirm_and_cancel():
    renderer = HtmlRenderer()
    renderer.apply(
        create_surface(
            "approve",
            [
                {
                    "id": "root",
                    "component": "ApprovalCard",
                    "title": "Review",
                    "slot_label": "Mon 09:00",
                    "reason": "Checkup",
                    "contact_method": "Email",
                    "patient_name": {"@path": "/patient/name"},
                }
            ],
            PATIENT_DATA,
        )
    )
    html_out = renderer.render_surface("approve")
    assert "Priya Sharma" in html_out
    assert "Confirm booking" in html_out
    assert "bookingConfirmed" in html_out
    assert "bookingCancelled" in html_out


def test_unknown_component_cannot_render():
    renderer = HtmlRenderer()
    renderer.apply(
        create_surface("x", [{"id": "root", "component": "EvilWidget"}], {})
    )
    with pytest.raises(RenderError, match="not in renderer catalog"):
        renderer.render_surface("x")


def test_missing_root_rejected():
    renderer = HtmlRenderer()
    renderer.apply(
        create_surface("x", [{"id": "a", "component": "Text", "text": "hi"}], {})
    )
    with pytest.raises(RenderError, match="no root"):
        renderer.render_surface("x")


def test_html_is_escaped():
    renderer = HtmlRenderer()
    renderer.apply(
        create_surface(
            "x",
            [{"id": "root", "component": "Text", "text": "<script>alert(1)</script>"}],
            {},
        )
    )
    html_out = renderer.render_surface("x")
    assert "<script>" not in html_out
    assert "&lt;script&gt;" in html_out
