"""FastAPI web UI: chat + server-rendered A2UI surfaces.

Endpoints:
  GET  /          chat page with the current surfaces rendered as HTML
  POST /chat      patient free-text message -> agent turn
  POST /action    renderer action (slot picked, intake submitted,
                  confirm/cancel) -> agent turn
  POST /function  A2UI 1.0 bidirectional RPC: the renderer calls an
                  agent function (checkAvailability) and gets an
                  agentFunctionResponse + updateDataModel back

Single in-memory session — this is a local demo, not a multi-tenant app.
Run offline (scripted demo model, no API key) or live (LiteLLM).
"""

from __future__ import annotations

import html
from datetime import date, timedelta
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .agent import A2UIBookingAgent, DemoModel, TurnResult
from .cli import DEMO_PATIENT
from .messages import agent_function_response, update_data_model
from .renderer import HtmlRenderer

PAGE_CSS = """
body{font-family:system-ui,sans-serif;max-width:720px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}
.a2ui-card{border:1px solid #d0d7de;border-radius:10px;padding:1rem;margin:1rem 0}
.a2ui-card h3{margin-top:0}
.slot{display:block;padding:.4rem 0}
.readonly,.row{display:flex;justify-content:space-between;padding:.25rem 0}
label{display:block;margin:.6rem 0}
input[type=text],select{width:100%;padding:.5rem;margin-top:.25rem;box-sizing:border-box}
button{background:#0969da;color:#fff;border:0;border-radius:6px;padding:.55rem 1.1rem;cursor:pointer;margin-top:.6rem}
button.secondary{background:#eaeef2;color:#1a1a1a;margin-left:.5rem}
.bar-row{display:flex;align-items:center;gap:.6rem;margin:.25rem 0}
.bar-row span:first-child{width:90px}
.bar{background:#2da44e;height:14px;border-radius:3px;min-width:2px}
.agent-text{color:#57606a;font-style:italic}
.chatbar{display:flex;gap:.5rem;margin-top:1.5rem}
.chatbar input{flex:1}
"""


def create_app(offline: bool = False, patient: dict[str, str] | None = None) -> FastAPI:
    app = FastAPI(title="agent-a2ui — Northside Clinic booking")
    today = date.today()
    agent = A2UIBookingAgent(
        patient=patient or DEMO_PATIENT,
        model_fn=DemoModel(today=today) if offline else None,
        today=today,
    )
    renderer = HtmlRenderer()
    session: dict[str, Any] = {"last_text": "", "context": {}}

    def apply_turn(turn: TurnResult) -> None:
        session["last_text"] = turn.text
        for message in turn.messages:
            renderer.apply(message)
        for surface in turn.surfaces:
            state = renderer.surfaces[surface["surface_id"]]
            state.data_model = surface["data_model"]

    def page() -> str:
        surfaces_html = renderer.render_all() if renderer.surfaces else (
            '<p class="agent-text">Ask me to book an appointment — '
            "I'll answer with a screen, not a wall of text.</p>"
        )
        agent_text = (
            f'<p class="agent-text">{html.escape(session["last_text"])}</p>'
            if session["last_text"]
            else ""
        )
        return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Northside Clinic — booking</title>
<style>{PAGE_CSS}</style></head><body>
<h2>Northside Clinic</h2>
{agent_text}
{surfaces_html}
<form class="chatbar" method="post" action="/chat">
  <input type="text" name="text" placeholder="e.g. Book me a checkup next week" required>
  <button type="submit">Send</button>
</form>
</body></html>"""

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return page()

    @app.post("/chat", response_class=HTMLResponse)
    def chat(text: str = Form(...)) -> str:
        apply_turn(agent.handle_user_text(text))
        return page()

    @app.post("/action", response_class=HTMLResponse)
    def action(
        action: str = Form(...),
        slot_id: str = Form(default=""),
        reason: str = Form(default=""),
        contact_method: str = Form(default=""),
    ) -> str:
        ctx: dict[str, Any] = dict(session["context"])
        if slot_id:
            ctx["slot_id"] = slot_id
            slot = agent.calendar.get_slot(slot_id)
            ctx["slot_label"] = slot.label if slot else slot_id
        if reason:
            ctx["reason"] = reason
        if contact_method:
            ctx["contact_method"] = contact_method
        session["context"] = ctx
        apply_turn(agent.handle_action(action, ctx))
        return page()

    @app.post("/function")
    async def function_call(request: Request) -> JSONResponse:
        """A2UI 1.0 bidirectional RPC: renderer -> agent function call.

        The renderer sends a callAgentFunction envelope; the agent
        executes the registered function against live calendar data and
        replies with agentFunctionResponse (+ updateDataModel so bound
        components refresh). Only catalog-registered functions run.
        """
        body = await request.json()
        call = body.get("callAgentFunction") or {}
        function_call_id = call.get("functionCallId", "")
        call_function = call.get("callFunction") or {}
        name = call_function.get("@call")
        args = call_function.get("args") or {}

        if name != "checkAvailability":
            return JSONResponse(
                agent_function_response(
                    function_call_id,
                    error={
                        "code": "INVALID_FUNCTION_CALL",
                        "message": f"function not registered: {name}",
                    },
                )
            )

        try:
            start = date.fromisoformat(args.get("start_date") or today.isoformat())
            end = date.fromisoformat(
                args.get("end_date") or (today + timedelta(days=7)).isoformat()
            )
        except ValueError as exc:
            return JSONResponse(
                agent_function_response(
                    function_call_id,
                    error={"code": "INVALID_ARGUMENT", "message": str(exc)},
                )
            )

        slots = [s.to_public() for s in agent.calendar.check_availability(start, end)]
        by_day = agent.calendar.availability_by_day(start, end)

        messages: list[dict[str, Any]] = [
            agent_function_response(function_call_id, value={"slots": slots})
        ]
        # Refresh any live picker surface with the new availability.
        for surface_id in list(renderer.surfaces):
            messages.append(update_data_model(surface_id, "/slots", slots))
            messages.append(
                update_data_model(surface_id, "/availability_by_day", by_day)
            )
        for message in messages:
            if "updateDataModel" in message:
                renderer.apply(message)
        return JSONResponse({"messages": messages})

    return app
