"""Ring the accepting doctor, read the summary, then join the sending doctor."""
import asyncio
from datetime import datetime, timezone
from html import escape
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

from services.shared import config
from services.sync_twilio.app.gather import validate_signature

router = APIRouter()
handoffs: dict[str, dict] = {}
TERMINAL = {"ended", "failed"}


def callback_url(token: str, kind: str) -> str:
    return f"https://{config.env('PUBLIC_HOST')}/handoff-status/{token}/{kind}"


def conference(room: str, token: str, role: str, end_on_exit: bool = True) -> str:
    end = "true" if end_on_exit else "false"
    # The first participant sets the callback for the entire conference.
    return (f'<Dial><Conference beep="false" endConferenceOnExit="{end}" participantLabel="{role}" '
            f'statusCallback="{escape(callback_url(token, "conference"))}" statusCallbackMethod="POST" '
            f'statusCallbackEvent="start end join leave">{escape(room)}</Conference></Dial>')


def call_callbacks(token: str, role: str) -> dict:
    return {"StatusCallback": callback_url(token, role), "StatusCallbackMethod": "POST",
            "StatusCallbackEvent": ["initiated", "ringing", "answered", "completed"]}


def progress(state: dict, status: str):
    if state["status"] in TERMINAL:
        return
    state["status"] = status
    if status == "connected":
        state.setdefault("connected_at", datetime.now(timezone.utc).isoformat())
    elif status in TERMINAL:
        state["ended_at"] = datetime.now(timezone.utc).isoformat()


def public_status(state: dict) -> dict:
    return {"mode": "live", **{key: state[key] for key in ("status", "connected_at", "ended_at") if key in state}}


@router.get("/handoffs/{transfer_id}")
def handoff_status(transfer_id: str):
    for state in reversed(list(handoffs.values())):
        if state["req"].transfer_id == transfer_id:
            return public_status(state)
    raise HTTPException(404)


@router.post("/handoff-status/{token}/{kind}")
async def status_callback(token: str, kind: str, request: Request):
    params = parse_qs((await request.body()).decode(), keep_blank_values=True)
    validate_signature(request, params)
    state = handoffs.get(token)
    if not state or kind not in {"conference", "accepting", "sending"}:
        raise HTTPException(404)
    values = {key: value[0] for key, value in params.items()}
    async with state["lock"]:
        event = values.get("StatusCallbackEvent", "")
        role = values.get("ParticipantLabel", "")
        # Conference events have a shared sequence, but one participant's late
        # join must still be processed after another participant's newer join.
        sequence_key = f"conference:{role}" if kind == "conference" else kind
        try:
            seq = int(values.get("SequenceNumber", "-1"))
        except ValueError:
            raise HTTPException(400, "Invalid callback sequence")
        if seq >= 0:
            if seq <= state["sequences"].get(sequence_key, -1):
                return Response(status_code=204)
            state["sequences"][sequence_key] = seq
        if kind == "conference":
            if event == "participant-join":
                state["joined"].add(role)
                if {"accepting", "sending"} <= state["joined"]:
                    progress(state, "connected")
            elif event == "participant-leave":
                state["joined"].discard(role)
                if role in {"accepting", "sending"}:
                    progress(state, "ended")
            elif event == "conference-end":
                progress(state, "ended")
        elif values.get("CallStatus") == "completed":
            progress(state, "ended")
        elif values.get("CallStatus") in {"busy", "failed", "no-answer", "canceled"}:
            progress(state, "failed")
    return Response(status_code=204)


async def start(req, hospital_entry: dict | None) -> dict:
    from services.sync_twilio.app.main import _twilio, _twiml_url
    token = uuid4().hex
    room = "uzima-" + token
    state = {"room": room, "req": req, "hospital": hospital_entry, "lock": asyncio.Lock(), "reply": None,
             "status": "calling_accepting_doctor", "joined": set(), "sequences": {}}
    handoffs[token] = state
    ready_url = f"https://{config.env('PUBLIC_HOST')}/doctor-ready/{token}"
    # The redirect happens only after the accepting doctor hears the summary.
    twiml = (f'<Response><Say>Hello, this is the Uzima AI assistant. {escape(req.summary or "I am calling about a demo referral.")}</Say>'
             f'<Redirect method="POST">{escape(ready_url)}</Redirect></Response>')
    try:
        result = await _twilio("Calls.json", {"To": req.accepting_doctor, "From": config.env("TWILIO_FROM_NUMBER"),
                                            "Url": _twiml_url(twiml), "Timeout": "30", "TimeLimit": "300",
                                            **call_callbacks(token, "accepting")})
    except httpx.HTTPError:
        progress(state, "failed")
        raise
    state["accepting_sid"] = result.get("sid")
    return {**public_status(state), "sid": result.get("sid"), "via": "doctor_conference"}


@router.post("/doctor-ready/{token}")
async def ready(token: str, request: Request):
    from services.sync_twilio.app.main import _twilio, _twiml_url
    params = parse_qs((await request.body()).decode(), keep_blank_values=True)
    validate_signature(request, params)
    state = handoffs.get(token)
    if not state:
        raise HTTPException(404)
    async with state["lock"]:
        if state["reply"] is not None:
            return Response(state["reply"], media_type="text/xml")
        if state["status"] in TERMINAL:
            return Response('<Response><Hangup/></Response>', media_type="text/xml")
        req = state["req"]
        try:
            sending = await _twilio("Calls.json", {"To": req.clinician or req.a,
                "From": config.env("TWILIO_FROM_NUMBER"), "Timeout": "30", "TimeLimit": "300",
                **call_callbacks(token, "sending"),
                "Url": _twiml_url('<Response><Say>The accepting doctor is joining your referral handoff.</Say>'
                                  + conference(state["room"], token, "sending") + '</Response>')})
            state["sending_sid"] = sending.get("sid")
            progress(state, "calling_sending_doctor")
            # Reception may leave without disconnecting the doctors.
            entry = state["hospital"] or {}
            if entry.get("call_sid"):
                try:
                    await _twilio(f'Calls/{entry["call_sid"]}.json', {"Url": _twiml_url(
                        '<Response><Say>The accepting and referring doctors are joining the handoff.</Say>'
                        + conference(state["room"], token, "hospital", end_on_exit=False) + '</Response>')})
                except httpx.HTTPError:
                    pass
            state["reply"] = ('<Response><Say>Connecting you to the referring doctor now.</Say>'
                              + conference(state["room"], token, "accepting") + '</Response>')
        except httpx.HTTPError:
            progress(state, "failed")
            # Cache the response so a repeated provider callback cannot redial.
            state["reply"] = '<Response><Say>We could not reach the referring doctor. Please contact them directly.</Say><Hangup/></Response>'
        return Response(state["reply"], media_type="text/xml")
