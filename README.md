# agent-a2ui — a booking agent that answers with screens, not text walls

Ask a typical agent to "book me a checkup next week" and you get a numbered
wall of text, then round after round of "which one?". Worse: to fill in any
form, the agent has to see your personal data — your name, phone, date of
birth — because everything flows through the model as text.

This project is a clinic appointment-booking agent built on **A2UI 1.0**,
Google's open protocol for generative UI (Apache 2.0). Instead of text, the
agent answers with interactive surfaces — a slot picker, an intake form, an
approval card — that the app renders with its own components.

## What is A2UI, in plain words?

The agent *describes* what to show as declarative JSON messages
(`createSurface`, `updateComponents`, `updateDataModel`, ...). The app
renders those messages natively, using **only the components the developer
registered in a catalog**. Two consequences matter:

1. **The agent cannot invent UI.** If it emits a component that isn't in
   your catalog — or props that don't match — validation rejects it before
   anything is drawn.
2. **Sensitive values never reach the model.** Components reference data
   with bindings like `{"@path": "/patient/name"}`. The model composes
   paths; the server fills in the values when the screen is drawn. The
   model never sees your name, phone, or date of birth.

A2UI 1.0 (Nov 2026) made the protocol stable and added bidirectional
function calls — a picker can check live availability on the spot.

Announcement: https://developers.googleblog.com/a2ui-10-build-delightful-fast-reliable-agentic-experiences/
Spec: https://a2ui.org/specification/v1.0-a2ui/ · Repo: https://github.com/a2ui-project/a2ui

## The flow

```
Patient: "Book me a checkup next week"
   │
   ▼
Agent calls check_availability ──► real open slots from the clinic calendar
   │
   ▼
SlotPicker surface (+ AvailabilityChart)     ← patient taps a slot
   │
   ▼
IntakeForm surface                           ← reason + contact method;
   │                                            name/phone/DOB shown read-only
   │                                            via /patient/* bindings
   ▼
ApprovalCard surface                         ← nothing booked yet
   │
   ▼  patient taps Confirm
book_appointment tool runs ──► InfoCard with confirmation code
```

The booking tool refuses to run until the patient confirms on the
ApprovalCard. That guardrail is enforced in code, not just in the prompt —
the model cannot set the confirmation flag itself.

## Architecture

```
┌──────────────────────────── server ────────────────────────────┐
│                                                                │
│  A2UIBookingAgent (agent.py)                                   │
│    system prompt: prompts.py (separate module, named constant) │
│    tools: check_availability / emit_surface / book_appointment │
│    model: LiteLLM, LLM_MODEL env (default gemini-3.5-flash-lite)│
│        │                                                       │
│        ▼ emit_surface                                          │
│  ClinicCatalog (catalog.py) — official A2UI SDK validation     │
│    7 registered components; anything else is rejected          │
│        │                                                       │
│        ▼ A2UI 1.0 messages (messages.py, SDK envelope schema)  │
│  binding.py — /patient/* attached server-side at render time   │
│        │                                                       │
│        ▼                                                       │
│  HtmlRenderer (renderer.py) ──► FastAPI web UI (web.py)        │
│  renderer actions POST back: slotSelected / intakeSubmitted /  │
│  bookingConfirmed / bookingCancelled                           │
│  POST /function — A2UI 1.0 callAgentFunction RPC               │
│  (checkAvailability → agentFunctionResponse + updateDataModel) │
└────────────────────────────────────────────────────────────────┘
```

Package layout (`src/agent_a2ui/`):

| Module | What it holds |
|---|---|
| `prompts.py` | The system prompt, as a named constant — never inline |
| `catalog.py` | The 7 component models + SDK catalog + validator |
| `messages.py` | A2UI 1.0 message builders + envelope validation |
| `binding.py` | JSON Pointer resolution; server-side patient injection |
| `tools.py` | Clinic calendar (real availability logic) + typed tool schemas |
| `agent.py` | `A2UIBookingAgent` — the visible agent class + loop |
| `renderer.py` | Server-side HTML renderer for A2UI surfaces |
| `cli.py` / `web.py` | One-command demo / FastAPI web UI |

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

# Full offline demo — prints the A2UI JSON for every step, no API key:
.venv/bin/python -m agent_a2ui demo

# Web UI, offline (scripted demo model, no API key):
.venv/bin/python -m agent_a2ui serve --offline

# Web UI, live model (LiteLLM; set LLM_MODEL + provider key):
GEMINI_API_KEY=... .venv/bin/python -m agent_a2ui serve

# Tests (44, all offline):
.venv/bin/python -m pytest -q

# Live end-to-end test against a real model:
.venv/bin/python scripts/live_test.py
```

## What's real, what's mock

**Real:**
- The agent loop — a real LLM plans, calls typed tools, composes surfaces,
  and reacts to renderer actions. Same loop code drives the live model and
  the offline scripted model.
- Catalog validation with the **official A2UI Python SDK**
  (`a2ui-agent-sdk` 0.12.0 / `a2ui-core` 0.7.0): component models extend
  the SDK's `ComponentCommon`, the catalog is an SDK `Catalog`, validation
  runs through the SDK's `PayloadValidator`, and every message is checked
  against the SDK's v1.0 `AgentToRendererMessage` schema.
- The A2UI 1.0 wire format: `{"version": "1.0", "createSurface": {...}}`
  envelopes, flat component lists with adjacency by id, `{"@path": ...}`
  bindings, `updateDataModel` refreshes, and `callAgentFunction` /
  `agentFunctionResponse` RPC on the `/function` endpoint.
- Availability logic: weekday clinic hours, pre-booked slots, bookings
  actually consume slots (book one and it disappears).
- The PII property, proven by test: everything the model produced or saw
  contains `/patient/*` paths only; the values appear solely in rendered
  HTML, resolved server-side.

**Mock / simplified (documented, not hidden):**
- The clinic calendar is deterministic in-memory data — no real EHR.
- The HTML renderer is mine. There is no official Python renderer for A2UI
  (official renderers are React, Angular, Lit, Flutter, SwiftUI, Jetpack
  Compose), so `renderer.py` is a small server-side stand-in that consumes
  the same messages a real renderer would.
- The agent loop uses LiteLLM tool-calling rather than the SDK's own
  inference formats (A2UI Express / Atom). The SDK is used where it
  matters most here — catalog definition, component validation, and the
  envelope schema — while LiteLLM keeps the live layer provider-agnostic
  (`LLM_MODEL` env var, swap models by config).
- `{"@call": ...}` bindings inside component props are not executed by the
  HTML renderer; live refresh goes through the `/function` RPC endpoint
  instead, which is the protocol's bidirectional-call path.
- Single in-memory session in the web UI; no auth, no persistence.

## Why these choices

- **Official SDK over hand-rolled JSON:** the catalog/validation story is
  the whole point of A2UI. Using Google's own validator means "the agent
  cannot invent UI" is enforced by the reference implementation, not by my
  say-so.
- **Custom catalog over the basic catalog:** a real app registers its own
  design-system components. This clinic registered exactly seven; even
  Google's basic `Button` is rejected here, and there's a test proving it.
- **LiteLLM over a single provider SDK:** the portfolio rule is
  provider-agnostic live layers — model from env, swap by config.
- **FastAPI server-rendered HTML over a JS framework:** the renderer is a
  teaching stand-in; server rendering keeps the whole example runnable
  with one command and zero build tooling.

## Limitations

- Live verification status: the offline suite (47 tests) passes with no API
  key. The live run (`scripts/live_test.py`) passed end to end on
  2026-11-25 on two real models — Gemini (`gemini-3.5-flash-lite`) and
  gpt-4o-mini — full flow (SlotPicker → IntakeForm → ApprovalCard →
  InfoCard), one booking created only after confirmation, and no patient
  PII in any model-emitted message. Getting there found two real
  portability bugs that the Gemini-only attempts had hidden: the system
  prompt never stated that a component object names its type in the
  `component` field (gpt-4o-mini guessed `type`, and the old validation
  error never said which key was wrong — both fixed), and stored history
  carried an empty `tool_calls` array that OpenAI rejects with a 400
  (Gemini tolerates it). Earlier live attempts (2026-11-23) failed on
  Gemini 503s and quota exhaustion before either bug could surface.
- The demo patient is fictional; the calendar is synthetic. No real
  healthcare data anywhere.
- Streaming/progressive rendering (a core A2UI feature) is not exercised —
  surfaces are sent whole per turn.
