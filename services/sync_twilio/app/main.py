"""Twilio demo calling and doctor handoff. Default speech uses Twilio and AWS Bedrock.
The legacy direct Realtime bridge is available only through VOICE_PROVIDER=openai_realtime.
Without enabled Twilio credentials endpoints return mock results.
"""
import asyncio
import base64
import json
import logging
from datetime import datetime, timezone
from html import escape
from typing import Any, Optional
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Response, WebSocket
from pydantic import BaseModel

from services.shared import config
from services.shared.clients import client
from services.shared.schemas import AgentHeader, AgentResult, CallEvent, Status, TranscriptLine
from services.sync_twilio.app import gather, doctor_handoff

app = FastAPI(title="Project Uzima Twilio gateway")
app.include_router(gather.router)
app.include_router(doctor_handoff.router)
log = logging.getLogger("sync_twilio")
outbox: list[dict] = []   # what was sent (or would have been, in mock mode), for the demo and tests
# (transfer_id, agent_id) -> {"header": dict, "transfer_id": str, "case_brief": str, "call_sid": str|None}
# Filled by POST /call, read by /media (same process). call_sid is set once the stream starts.
live_calls: dict[tuple[str, str], dict] = {}
# id -> TwiML document. Twilio is sent Url=https://PUBLIC_HOST/twiml/{id} instead of inline Twiml=
# (inline Twiml= is rejected on our account: "trial accounts have limited parameter access").
twiml_docs: dict[str, str] = {}

HANDOFF_MIN = 10              # same as call_sim.HANDOFF_MIN
CLOSING_MAX_S = 12.0          # after the tool call, stop the model this long later even if playback never confirmed
MAX_CALL_S = float(config.env("LIVE_CALL_MAX_S", "240"))   # no report by then (voicemail, silence): hang up as no_answer
SPECIALTY_NEED = {
    "cardiac_icu": "a STEMI patient who needs a cath lab and a cardiac ICU bed",
    "stroke_thrombectomy": "a large vessel stroke patient who needs thrombectomy and a neuro ICU bed",
    "trauma_adult": "an adult trauma patient who needs a trauma bay and a surgical team",
    "trauma_burn": "a burn patient who needs a burn ICU bed",
    "childbirth": "a high-risk delivery who needs labor and delivery, an emergency C-section team and a NICU bed",
    "trauma_pediatric": "a pediatric trauma patient who needs a pediatric trauma bay",
}


class CallRequest(BaseModel):
    header: dict
    transfer_id: str
    case_brief: str = ""      # one breath the agent says after the AI disclosure; built from the header if empty


class SmsRequest(BaseModel):
    to: str
    text: str


class ReleaseRequest(BaseModel):
    hospital: str
    phone: str


class BridgeRequest(BaseModel):
    transfer_id: str = ""
    agent_id: str = ""
    summary: str = ""              # read to the accepting hospital before the doctors are connected
    clinician: str = ""            # referring clinician's phone (the Connect button)
    accepting_doctor: str = ""     # separate receiving doctor; summary before clinician is dialed
    fallback_hospital: str = ""    # used when the winner was a simulated hospital with no live call
    a: str = ""                    # legacy: dial a, then connect b
    b: str = ""


async def _twilio(path: str, data: dict) -> dict:
    sid = config.env("TWILIO_ACCOUNT_SID")
    async with httpx.AsyncClient(timeout=20, auth=(sid, config.env("TWILIO_AUTH_TOKEN"))) as c:
        r = await c.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/{path}", data=data)
        r.raise_for_status()
        return r.json()


def _mock(kind: str, **payload) -> dict:
    outbox.append({"kind": kind, **payload})
    log.info("MOCK %s %s", kind, payload)
    return {"mode": "mock", "kind": kind}


def _twiml_url(twiml: str) -> str:
    """Store a TwiML document and return the public URL Twilio fetches it from (GET /twiml/{id})."""
    doc_id = uuid4().hex
    twiml_docs[doc_id] = twiml
    return f"https://{config.env('PUBLIC_HOST')}/twiml/{doc_id}"


@app.api_route("/twiml/{doc_id}", methods=["GET", "POST"])
def twiml_doc(doc_id: str):
    """Twilio fetches call instructions here (POST by default)."""
    if doc_id not in twiml_docs:
        raise HTTPException(404, "unknown twiml id")
    return Response(content=twiml_docs[doc_id], media_type="text/xml")


@app.post("/call")
async def call(req: CallRequest):
    agent_id = str(req.header.get("agent_id", ""))
    live_calls[(req.transfer_id, agent_id)] = {"header": req.header, "transfer_id": req.transfer_id,
                                               "case_brief": req.case_brief, "call_sid": None}
    if not config.has_twilio():
        return _mock("call", to=req.header.get("phone"), agent=req.header.get("agent_id"))
    public = config.env("PUBLIC_HOST")   # ngrok host, e.g. abcd.ngrok-free.app
    if not public or "://" in public or "/" in public:
        raise HTTPException(503, "Set PUBLIC_HOST to the reachable HTTPS callback hostname.")
    sending = config.env("SENDING_HOSPITAL_NAME", "South Sunflower County Hospital")
    greeting = f"Hello, this is an AI assistant calling for {sending} about a patient transfer. Please hold one moment."
    twiml = (f'<Response>'
             f'<Say>{escape(greeting)}</Say>'
             f'<Connect><Stream url="wss://{public}/media">'
             f'<Parameter name="transfer_id" value="{escape(req.transfer_id)}"/>'
             f'<Parameter name="agent_id" value="{escape(req.header["agent_id"])}"/>'
             f'</Stream></Connect></Response>')
    provider = config.env("VOICE_PROVIDER", "bedrock_gather")
    if provider == "bedrock_gather":
        h = AgentHeader(**req.header)
        twiml = await gather.start(h, req.transfer_id, req.case_brief or default_brief(h))
    elif provider != "openai_realtime":
        raise HTTPException(503, "Unknown VOICE_PROVIDER")
    # Pause once after pickup, before either provider starts its first greeting.
    twiml = twiml.replace("<Response>", '<Response><Pause length="1"/>', 1)
    r = await _twilio("Calls.json", {"To": req.header["phone"], "From": config.env("TWILIO_FROM_NUMBER"), "Url": _twiml_url(twiml),
                                    "Timeout": "30", "TimeLimit": str(int(MAX_CALL_S) + 180)})
    live_calls[(req.transfer_id, agent_id)]["call_sid"] = r.get("sid")
    return {"mode": "live", "sid": r.get("sid")}


# ---------------------------------------------------------------- pure logic (unit tested in tests/test_bridge.py)

def _now() -> datetime:
    return datetime.now(timezone.utc)


def default_brief(h: AgentHeader) -> str:
    need = SPECIALTY_NEED.get(h.specialty.value, f"a patient who needs {h.specialty.value.replace('_', ' ')}")
    sending = config.env("SENDING_HOSPITAL_NAME", "South Sunflower County Hospital")
    return f"I'm calling for a doctor at {sending} about {need}, and we'd like to transfer them to {h.hospital}."


def build_instructions(h: AgentHeader, brief: str) -> str:
    q = h.capability_question
    return f"""You are an AI assistant making a phone call to the transfer desk at {h.hospital} for a referring clinician.
Speak English, calmly and briefly, like a professional on a busy phone line. One or two short sentences per turn.

Your first line must be exactly in this spirit, in one breath:
"Hi, this is an AI assistant calling for a referring doctor. {brief} {q}"
If you are interrupted during that first line, say it again briefly.

Goal: get two facts. 1) The answer to: "{q}" 2) If yes, how many minutes until they could be ready to receive the patient.
- If they say no, ask the reason in one short question (for example "What's the main reason?").
- Never invent or guess an answer. If an answer is unclear, ask again once. If they still won't or can't answer, treat it as no with reason "unclear".
- Before reporting, READ THE ANSWER BACK, for example "So that's yes, you can take the patient, ready in 10 minutes, is that right?" or "So that's a no because there's no staffed bed, is that right?"
- Only after they confirm, call the tool report_capacity with confirmed=true. If they correct you, fix it and read back again.
- After the tool call: if yes, say "Thank you, please hold while I confirm with the doctor." and then say nothing more. If no, say "Thank you, goodbye."
- You cannot share patient identifiers and you do not make medical decisions. If they ask for details you don't have, say the doctor will give them on the handoff.
"""


REPORT_TOOL = {
    "type": "function",
    "name": "report_capacity",
    "description": "Record the hospital's answer. Call only after reading the answer back and the hospital confirmed it.",
    "parameters": {
        "type": "object",
        "properties": {
            "bed": {"type": "boolean", "description": "True if they can take the patient now."},
            "ready_in_min": {"type": ["integer", "null"], "description": "Minutes until they could receive the patient, if yes."},
            "reason": {"type": ["string", "null"], "description": "Short reason if no, e.g. 'no staffed bed', 'unclear'."},
            "confirmed": {"type": "boolean", "description": "True if the hospital confirmed the read-back."},
        },
        "required": ["bed", "ready_in_min", "reason", "confirmed"],
    },
}


def _to_min(v: Any) -> Optional[int]:
    try:
        return None if v is None or v == "" else max(0, int(round(float(v))))
    except (TypeError, ValueError):
        return None


def answer_data(args: dict) -> dict:
    """report_capacity args -> the answer_recorded CallEvent data {bed, ready_in_min, reason}."""
    bed = args.get("bed") is True or str(args.get("bed")).lower() == "true"
    ready = _to_min(args.get("ready_in_min")) if bed else None
    reason = None if bed else ((args.get("reason") or "").strip() or "unclear")
    return {"bed": bed, "ready_in_min": ready, "reason": reason}


def build_result(h: AgentHeader, transfer_id: str, args: Optional[dict], transcript: list[TranscriptLine],
                 answered_at: Optional[datetime] = None) -> tuple[str, AgentResult]:
    """(outcome for call_ended, AgentResult). args=None means nothing was reported -> no_answer."""
    lines = sorted(transcript, key=lambda l: l.at)
    base = dict(transfer_id=transfer_id, agent_id=h.agent_id, hospital_id=h.hospital_id, hospital=h.hospital, lat=h.lat, lng=h.lng,
                transport=h.transport, transcript=lines, answered_at=answered_at, source="live")
    if args is None:
        return Status.no_answer.value, AgentResult(status=Status.no_answer, **base)
    d = answer_data(args)
    t = h.transport
    travel = t.est_ground_min if t.recommended_mode == "ground" else t.est_air_min
    ready = d["ready_in_min"]
    status = Status.available if d["bed"] else Status.declined
    res = AgentResult(status=status, ready_in_min=ready, decline_reason=d["reason"],
                      treatment_start_min=(max(travel, ready) + HANDOFF_MIN) if ready is not None else None,
                      **{**base, "answered_at": answered_at or _now()})
    return status.value, res


# ---------------------------------------------------------------- Twilio <-> OpenAI Realtime bridge

def _openai_connect():
    """GA Realtime websocket. No 'OpenAI-Beta: realtime=v1' header: that selects the old beta shapes."""
    model = config.env("OPENAI_REALTIME_MODEL", "gpt-realtime")
    url = f"wss://api.openai.com/v1/realtime?model={model}"
    headers = {"Authorization": f"Bearer {config.env('OPENAI_API_KEY')}"}
    try:   # websockets >= 13: new asyncio client
        from websockets.asyncio.client import connect
        return connect(url, additional_headers=headers, max_size=None)
    except ImportError:   # websockets 12: legacy client
        from websockets import connect
        return connect(url, extra_headers=headers, max_size=None)


class Bridge:
    def __init__(self, ws: WebSocket, header: AgentHeader, transfer_id: str, brief: str, stream_sid: str, call_sid: Optional[str]):
        self.ws, self.h, self.tid, self.brief = ws, header, transfer_id, brief
        self.stream_sid, self.call_sid = stream_sid, call_sid
        self.oai = None
        self.transcript: list[TranscriptLine] = []
        self.item_at: dict[str, datetime] = {}     # item_id -> when that turn started, to order transcript lines
        self.answered_at: Optional[datetime] = None
        self.report: Optional[dict] = None
        self.need_response = False                 # a tool output was sent; create a response once the current one is done
        self.response_active = False
        self.awaiting_closing = False
        self.closing_rid: Optional[str] = None
        self.muted = False                         # model output no longer goes to the phone
        self.finishing = False
        self.finalized = False
        self.ws_closed = False
        self._emit_q: asyncio.Queue = asyncio.Queue()
        self._tasks: list[asyncio.Task] = []

    # -- collector (sequential, non-blocking for audio, failures only logged)
    def emit(self, kind: str, payload: dict) -> None:
        self._emit_q.put_nowait((kind, payload))

    def event(self, event_type: str, **data) -> None:
        ev = CallEvent(type=event_type, transfer_id=self.tid, agent_id=self.h.agent_id, hospital_id=self.h.hospital_id, at=_now(), data=data)
        self.emit("/events", ev.model_dump(mode="json"))

    async def _emit_worker(self) -> None:
        while True:
            item = await self._emit_q.get()
            if item is None:
                return
            path, payload = item
            try:
                async with client("collector") as c:
                    (await c.post(path, json=payload)).raise_for_status()
            except Exception as e:
                log.warning("collector POST %s failed: %s", path, e)

    # -- sends that never raise
    async def to_twilio(self, msg: dict) -> None:
        try:
            await self.ws.send_json(msg)
        except Exception as e:
            log.debug("twilio send failed: %s", e)

    async def close_ws(self) -> None:
        if self.ws_closed:
            return
        self.ws_closed = True
        try:
            await self.ws.close()
        except Exception:
            pass

    async def to_ai(self, msg: dict) -> None:
        if self.oai is None:
            return
        try:
            await self.oai.send(json.dumps(msg))
        except Exception as e:
            log.debug("openai send failed: %s", e)

    def later(self, coro) -> None:
        self._tasks.append(asyncio.create_task(coro))

    # -- lifecycle
    async def run(self) -> None:
        worker = asyncio.create_task(self._emit_worker())
        self.event("call_started")
        self.later(self._watchdog())
        try:
            if not config.has_openai():
                log.warning("OPENAI_API_KEY missing: live call has no voice; playing apology")
                await self.play_apology_and_hangup()
                await self._from_twilio()
            else:
                await self._bridge()
        except Exception as e:
            log.exception("bridge error: %s", e)
        finally:
            self.finalize()
            for t in self._tasks:
                t.cancel()
            self._emit_q.put_nowait(None)
            try:
                await asyncio.wait_for(worker, timeout=15)
            except Exception:
                worker.cancel()

    async def _bridge(self) -> None:
        try:
            conn = _openai_connect()
            self.oai = await conn
        except Exception as e:
            log.error("could not start OpenAI Realtime session: %s", e)
            await self.play_apology_and_hangup()
            await self.close_ws()
            return
        await self._setup()
        t_tw = asyncio.create_task(self._from_twilio())
        t_ai = asyncio.create_task(self._from_openai())
        done, _ = await asyncio.wait({t_tw, t_ai}, return_when=asyncio.FIRST_COMPLETED)
        if t_tw in done:          # call ended (stop / hangup / disconnect)
            t_ai.cancel()
            await self._close_ai()
            return
        if t_ai.exception():
            log.warning("openai side ended: %r", t_ai.exception())
        if self.finishing:        # we closed OpenAI on purpose: yes -> hospital on hold; no -> hangup already sent
            await t_tw            # returns when Twilio sends stop / closes
            return
        log.warning("OpenAI connection dropped before a report; ending call")   # no voice left, don't leave them hanging
        await self.hangup()
        await self.close_ws()
        t_tw.cancel()

    async def _setup(self) -> None:
        # GA session shape (type "realtime", audio.input/output). Beta used input_audio_format "g711_ulaw" and
        # response.audio.delta; GA uses {"type": "audio/pcmu"} and response.output_audio.delta.
        await self.to_ai({"type": "session.update", "session": {
            "type": "realtime",
            "model": config.env("OPENAI_REALTIME_MODEL", "gpt-realtime"),
            "output_modalities": ["audio"],
            "instructions": build_instructions(self.h, self.brief),
            "audio": {
                "input": {"format": {"type": "audio/pcmu"},
                          "transcription": {"model": config.env("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe"), "language": "en"},
                          "turn_detection": {"type": "server_vad", "silence_duration_ms": 600}},
                "output": {"format": {"type": "audio/pcmu"}, "voice": config.env("OPENAI_REALTIME_VOICE", "alloy")},
            },
            "tools": [REPORT_TOOL],
            "tool_choice": "auto",
        }})
        # Speak first: a short user-role nudge, then a response.
        await self.to_ai({"type": "conversation.item.create", "item": {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "(The hospital desk just picked up the phone. Say your first line now.)"}]}})
        await self.to_ai({"type": "response.create"})

    async def _close_ai(self) -> None:
        if self.oai is not None:
            try:
                await self.oai.close()
            except Exception:
                pass

    async def _from_twilio(self) -> None:
        try:
            await self._twilio_loop()
        except RuntimeError:   # we closed the socket ourselves
            pass

    async def _twilio_loop(self) -> None:
        if self.ws_closed:
            return
        async for msg in self.ws.iter_json():
            ev = msg.get("event")
            if ev == "media":
                if not self.finishing:
                    await self.to_ai({"type": "input_audio_buffer.append", "audio": msg["media"]["payload"]})
            elif ev == "mark":
                if (msg.get("mark") or {}).get("name") == "closing":
                    self.later(self.finish_talking(delay=0.5))
            elif ev == "stop":
                return

    async def _from_openai(self) -> None:
        async for raw in self.oai:
            m = json.loads(raw)
            t = m.get("type", "")
            if t == "response.output_audio.delta":
                self.item_at.setdefault(m.get("item_id", ""), _now())
                if not self.muted:
                    await self.to_twilio({"event": "media", "streamSid": self.stream_sid, "media": {"payload": m["delta"]}})
            elif t == "input_audio_buffer.speech_started":
                self.item_at[m.get("item_id", "")] = _now()
                if self.answered_at is None:
                    self.answered_at = _now()
                    self.event("call_answered")
                await self.to_twilio({"event": "clear", "streamSid": self.stream_sid})   # barge-in: drop queued audio
                if self.response_active:
                    await self.to_ai({"type": "response.cancel"})
            elif t == "response.created":
                self.response_active = True
                if self.awaiting_closing and self.closing_rid is None:
                    self.closing_rid = (m.get("response") or {}).get("id")
            elif t == "response.done":
                self.response_active = False
                rid = (m.get("response") or {}).get("id")
                if self.need_response:              # the response that carried the tool call is over
                    self.need_response = False
                    if self.report is not None:
                        self.awaiting_closing, self.closing_rid = True, None
                    await self.to_ai({"type": "response.create"})
                elif self.awaiting_closing and rid and rid == self.closing_rid:
                    # Twilio echoes this mark once everything before it has played: then the closing line is heard.
                    await self.to_twilio({"event": "mark", "streamSid": self.stream_sid, "mark": {"name": "closing"}})
            elif t == "conversation.item.input_audio_transcription.completed":
                text = (m.get("transcript") or "").strip()
                if text:
                    self.transcript.append(TranscriptLine(speaker="hospital", text=text, at=self.item_at.get(m.get("item_id", ""), _now())))
            elif t == "response.output_audio_transcript.done":
                text = (m.get("transcript") or "").strip()
                if text:
                    self.transcript.append(TranscriptLine(speaker="agent", text=text, at=self.item_at.get(m.get("item_id", ""), _now())))
            elif t == "response.function_call_arguments.done":
                await self._on_tool(m)
            elif t == "error":
                err = m.get("error") or {}
                if err.get("code") not in ("response_cancel_not_active", "no_active_response"):
                    log.warning("openai error: %s", err)

    async def _on_tool(self, m: dict) -> None:
        call_id = m.get("call_id")
        try:
            args = json.loads(m.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        if m.get("name") != "report_capacity":
            out = {"ok": False, "error": "unknown tool"}
        elif self.report is not None:
            out = {"ok": True, "note": "already recorded, do not call again"}
        elif not isinstance(args, dict) or args.get("confirmed") is not True:
            out = {"ok": False, "error": "Not recorded. Read the answer back, get their confirmation, then call again with confirmed=true."}
        else:
            self.report = args
            data = answer_data(args)
            self.event("answer_recorded", **data)
            out = {"ok": True, "recorded": data}
            self.later(self.finish_talking(delay=CLOSING_MAX_S))   # fallback if the closing mark never comes back
        await self.to_ai({"type": "conversation.item.create", "item": {"type": "function_call_output", "call_id": call_id,
                                                                       "output": json.dumps(out)}})
        if not (self.report is not None and out.get("note")):
            self.need_response = True
            if not self.response_active:            # response.done already came (unusual ordering)
                self.need_response = False
                if self.report is not None:
                    self.awaiting_closing, self.closing_rid = True, None
                await self.to_ai({"type": "response.create"})

    async def finish_talking(self, delay: float = 0.0) -> None:
        """After the closing line: no -> hang up; yes -> stop the model but keep the hospital on the line (hold)."""
        if delay:
            await asyncio.sleep(delay)
        if self.finishing:
            return
        self.finishing = True
        self.muted = True
        self.finalize()
        await self._close_ai()
        if self.report is None or not answer_data(self.report)["bed"]:
            await self.hangup()

    async def _watchdog(self) -> None:
        await asyncio.sleep(MAX_CALL_S)
        if self.report is None and not self.finishing:
            log.warning("no report after %ss; hanging up", MAX_CALL_S)
            await self.finish_talking()

    async def play_apology_and_hangup(self) -> None:
        """Play a short apology when the OpenAI Realtime session fails to START.
        Must only be called before a Realtime session has been established.
        Never call after a healthy Realtime session has already begun."""
        apology = (
            "We are sorry, we encountered a technical difficulty and cannot complete this call. "
            "Please try again shortly. Goodbye."
        )
        twiml = f"<Response><Say>{escape(apology)}</Say><Hangup/></Response>"
        if self.call_sid and config.has_twilio():
            try:
                await _twilio(f"Calls/{self.call_sid}.json", {"Url": _twiml_url(twiml)})
                return
            except Exception as e:
                log.warning("apology TwiML update failed (%s); falling back to silent hangup", e)
        await self.hangup()

    async def hangup(self) -> None:
        if not (self.call_sid and config.has_twilio()):
            await self.close_ws()   # ending the <Connect> stream with no further TwiML ends the call too
            return
        try:
            await _twilio(f"Calls/{self.call_sid}.json", {"Status": "completed"})
        except Exception as e:
            log.warning("twilio hangup failed (%s); closing the stream instead", e)
            await self.close_ws()

    def finalize(self) -> None:
        """call_ended + AgentResult, exactly once."""
        if self.finalized:
            return
        self.finalized = True
        outcome, result = build_result(self.h, self.tid, self.report, self.transcript, self.answered_at)
        self.event("call_ended", outcome=outcome)
        self.emit("/results", result.model_dump(mode="json"))


@app.websocket("/media")
async def media(ws: WebSocket):
    """Twilio Media Stream <-> OpenAI Realtime. Emits call_started, call_answered, answer_recorded, call_ended + AgentResult."""
    await ws.accept()
    start = None
    async for msg in ws.iter_json():
        if msg.get("event") == "start":
            start = msg.get("start") or {}
            break
        if msg.get("event") == "stop":
            return
    if start is None:
        return
    params = start.get("customParameters") or {}
    key = (params.get("transfer_id", ""), params.get("agent_id", ""))
    entry = live_calls.get(key)
    if entry is None:
        log.error("media stream for unknown call %s; hanging up", key)
        await ws.close()
        return
    entry["call_sid"] = start.get("callSid") or entry.get("call_sid")
    header = AgentHeader(**entry["header"])
    brief = (entry.get("case_brief") or "").strip() or default_brief(header)
    await Bridge(ws, header, entry["transfer_id"], brief, start.get("streamSid"), entry["call_sid"]).run()


@app.post("/sms")
async def sms(req: SmsRequest):
    if not config.has_twilio():
        return _mock("sms", to=req.to, text=req.text)
    r = await _twilio("Messages.json", {"To": req.to, "From": config.env("TWILIO_FROM_NUMBER"), "Body": req.text})
    return {"mode": "live", "sid": r.get("sid")}


@app.post("/release")
async def release(req: ReleaseRequest):
    """Hospitals never get texts or links. The agent already thanked them on the call, so this only logs."""
    return _mock("release", hospital=req.hospital, phone=req.phone)


@app.post("/bridge")
async def bridge(req: BridgeRequest):
    """Connect doctor to doctor. If the winner is on a live call (on hold after saying yes), update that call:
    the agent reads the summary, then Twilio dials the referring clinician into it. Otherwise call the receiving
    doctor first, read the summary and then dial the referring clinician."""
    entry = live_calls.get((req.transfer_id, req.agent_id)) if req.transfer_id else None
    say = f"<Say>{escape(req.summary)}</Say>" if req.summary else ""
    if not config.has_twilio():
        return _mock("bridge", live=bool(entry), clinician=req.clinician or req.a, summary=req.summary)
    if req.accepting_doctor:
        return await doctor_handoff.start(req, entry)
    if entry and entry.get("call_sid"):
        twiml = f"<Response>{say}<Dial>{escape(req.clinician or req.a)}</Dial></Response>"
        try:
            r = await _twilio(f"Calls/{entry['call_sid']}.json", {"Url": _twiml_url(twiml)})
            return {"mode": "live", "sid": r.get("sid"), "via": "live_call"}
        except httpx.HTTPStatusError as e:
            if not (req.fallback_hospital or req.b):
                raise
            log.warning("Twilio rejected live-call update (HTTP %s); using configured fallback", e.response.status_code)
    to, other = (req.clinician or req.a), (req.fallback_hospital or req.b)
    # The receiving doctor hears the referral before the referring clinician joins.
    twiml = f"<Response>{say or '<Say>This is the Uzima AI assistant connecting the referring doctor.</Say>'}<Dial>{escape(to)}</Dial></Response>"
    r = await _twilio("Calls.json", {"To": other, "From": config.env("TWILIO_FROM_NUMBER"), "Url": _twiml_url(twiml)})
    return {"mode": "live", "sid": r.get("sid"), "via": "new_call"}


@app.get("/outbox")
def get_outbox():
    return outbox


@app.get("/health")
def health():
    return {"ok": True, "mode": "live" if config.has_twilio() else "mock",
            "voice_provider": config.env("VOICE_PROVIDER", "bedrock_gather"),
            "bedrock_enabled": config.has_bedrock(), "public_callback_configured": bool(config.env("PUBLIC_HOST"))}
