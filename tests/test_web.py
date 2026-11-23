"""Web UI: full booking flow over HTTP with the offline demo model."""

from fastapi.testclient import TestClient

from agent_a2ui.web import create_app


def make_client() -> TestClient:
    return TestClient(create_app(offline=True))


def test_home_page_loads():
    client = make_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Northside Clinic" in resp.text


def test_full_flow_over_http():
    client = make_client()

    resp = client.post("/chat", data={"text": "Book me a checkup next week"})
    assert resp.status_code == 200
    assert "Pick a time" in resp.text
    assert 'name="slot_id"' in resp.text

    # Extract a slot id from the rendered picker.
    import re

    match = re.search(r'name="slot_id" value="([^"]+)"', resp.text)
    assert match, "no slot radio rendered"
    slot_id = match.group(1)

    resp = client.post(
        "/action", data={"action": "slotSelected", "slot_id": slot_id}
    )
    assert "Reason for visit" in resp.text
    assert "Priya Sharma" in resp.text  # resolved server-side

    resp = client.post(
        "/action",
        data={
            "action": "intakeSubmitted",
            "reason": "Annual checkup",
            "contact_method": "Text message",
        },
    )
    assert "Review your booking" in resp.text
    assert "Confirm booking" in resp.text

    resp = client.post("/action", data={"action": "bookingConfirmed"})
    assert "booked" in resp.text  # InfoCard title (apostrophe is HTML-escaped)
    assert "NCK-" in resp.text


def test_function_call_rpc():
    """A2UI 1.0 bidirectional RPC: renderer calls checkAvailability."""
    client = make_client()
    resp = client.post(
        "/function",
        json={
            "version": "1.0",
            "callAgentFunction": {
                "functionCallId": "rpc-1",
                "callFunction": {
                    "@call": "checkAvailability",
                    "catalogId": "https://northside-clinic.example/a2ui/catalogs/clinic/catalog.json",
                    "args": {},
                },
            },
        },
    )
    assert resp.status_code == 200
    messages = resp.json()["messages"]
    first = messages[0]
    assert "agentFunctionResponse" in first
    assert first["agentFunctionResponse"]["functionCallId"] == "rpc-1"
    assert first["agentFunctionResponse"]["value"]["slots"]


def test_unregistered_function_rejected():
    client = make_client()
    resp = client.post(
        "/function",
        json={
            "version": "1.0",
            "callAgentFunction": {
                "functionCallId": "rpc-2",
                "callFunction": {"@call": "deleteEverything", "args": {}},
            },
        },
    )
    first = resp.json()["messages"][0] if "messages" in resp.json() else resp.json()
    assert first["agentFunctionResponse"]["error"]["code"] == "INVALID_FUNCTION_CALL"
