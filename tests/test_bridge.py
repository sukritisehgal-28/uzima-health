"""Pure logic of the live call bridge: report_capacity args -> answer_recorded data + AgentResult. Offline."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from fastapi.testclient import TestClient

from services.shared.schemas import AgentHeader, Status, TranscriptLine
from services.sync_twilio.app.main import (Bridge, _twiml_url, answer_data, app,
                                         build_instructions, build_result, default_brief, twiml_docs)
from services.sync_twilio.app import main as gateway

H = AgentHeader(agent_id="A1", hospital_id="greenville", hospital="Delta Regional", phone="+15550100", lat=33.4, lng=-91.0,
                specialty="cardiac_icu", capability_question="Do you have a cardiac ICU bed and a cath lab team available right now?",
                transport={"est_ground_min": 35, "est_air_min": 18, "recommended_mode": "ground", "tier": "within_target"}, live=True)


def test_bed_yes_is_available_with_treatment_start():
    args = {"bed": True, "ready_in_min": 10, "reason": None, "confirmed": True}
    assert answer_data(args) == {"bed": True, "ready_in_min": 10, "reason": None}
    t0 = datetime.now(timezone.utc)
    lines = [TranscriptLine(speaker="hospital", text="Yes, ten minutes.", at=t0 + timedelta(seconds=5)),
             TranscriptLine(speaker="agent", text="Hi, this is an AI assistant.", at=t0)]
    outcome, r = build_result(H, "T1", args, lines, answered_at=t0)
    assert outcome == "available" and r.status == Status.available
    assert r.ready_in_min == 10 and r.decline_reason is None
    assert r.treatment_start_min == max(35, 10) + 10          # ground travel dominates
    assert [l.speaker for l in r.transcript] == ["agent", "hospital"]   # sorted by time
    assert r.transfer_id == "T1" and r.agent_id == "A1" and r.answered_at == t0


def test_ready_longer_than_travel_and_air_mode():
    h = H.model_copy(update={"transport": H.transport.model_copy(update={"recommended_mode": "air"})})
    _, r = build_result(h, "T1", {"bed": True, "ready_in_min": "25", "confirmed": True}, [])
    assert r.treatment_start_min == max(18, 25) + 10


def test_bed_no_is_declined_with_reason():
    args = {"bed": False, "ready_in_min": 5, "reason": "no staffed bed", "confirmed": True}
    assert answer_data(args) == {"bed": False, "ready_in_min": None, "reason": "no staffed bed"}
    outcome, r = build_result(H, "T1", args, [])
    assert outcome == "declined" and r.status == Status.declined
    assert r.decline_reason == "no staffed bed" and r.ready_in_min is None and r.treatment_start_min is None


def test_bed_no_without_reason_is_unclear():
    assert answer_data({"bed": False, "reason": ""})["reason"] == "unclear"


def test_nothing_reported_is_no_answer():
    outcome, r = build_result(H, "T1", None, [])
    assert outcome == "no_answer" and r.status == Status.no_answer and r.treatment_start_min is None


def test_instructions_disclose_ai_and_ask_question():
    text = build_instructions(H, default_brief(H))
    assert "AI assistant" in text and H.capability_question in text and "report_capacity" in text
    assert "Delta Regional" in default_brief(H)


def test_twiml_served_by_url_for_get_and_post(monkeypatch):
    monkeypatch.setenv("PUBLIC_HOST", "abcd.ngrok-free.app")
    twiml = '<Response><Say>Hi &amp; bye</Say><Dial>+15550100</Dial></Response>'
    url = _twiml_url(twiml)
    assert url.startswith("https://abcd.ngrok-free.app/twiml/")
    path = url.removeprefix("https://abcd.ngrok-free.app")
    tc = TestClient(app)
    for r in (tc.post(path), tc.get(path)):
        assert r.status_code == 200 and r.text == twiml
        assert r.headers["content-type"].startswith("text/xml")
    assert tc.post("/twiml/nope").status_code == 404


def test_call_twiml_greeting_exercises_real_production_path(monkeypatch):
    """Req 1: POST /call stores TwiML with exact greeting before <Connect>; Url= used; no inline Twiml=.
    Monkeypatches _twilio so no network call occurs. Captures the Url sent to Twilio,
    resolves the stored TwiML from twiml_docs, and asserts on the real generated content."""
    monkeypatch.setenv("VOICE_PROVIDER", "openai_realtime")
    monkeypatch.setenv("PUBLIC_HOST", "test.ngrok-free.app")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "toktest")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15550000")

    captured = {}

    async def fake_twilio(path: str, data: dict) -> dict:
        captured["path"] = path
        captured["data"] = data
        return {"sid": "SIM_SID"}

    twiml_docs.clear()

    with patch("services.sync_twilio.app.main._twilio", new=fake_twilio):
        tc = TestClient(app)
        resp = tc.post("/call", json={
            "header": {
                "agent_id": "A1",
                "hospital_id": "greenville",
                "hospital": "Delta Regional",
                "phone": "+15559999",
                "lat": 33.4,
                "lng": -91.0,
                "specialty": "cardiac_icu",
                "capability_question": "Do you have a cardiac ICU bed?",
                "transport": {"est_ground_min": 35, "est_air_min": 18,
                              "recommended_mode": "ground", "tier": "within_target"},
                "live": True,
            },
            "transfer_id": "TXTEST1",
            "case_brief": "",
        })

    assert resp.status_code == 200, resp.text

    # 8. Twilio call creation uses Url=
    assert "Url" in captured["data"]
    # 9. Twilio call creation does NOT use inline Twiml=
    assert "Twiml" not in captured["data"]

    # Resolve the real TwiML from the URL stored by production code
    twiml_url = captured["data"]["Url"]
    assert twiml_url.startswith("https://test.ngrok-free.app/twiml/")
    doc_id = twiml_url.removeprefix("https://test.ngrok-free.app/twiml/")
    assert doc_id in twiml_docs, "twiml_docs must contain the generated document"
    twiml = twiml_docs[doc_id]

    assert twiml.startswith('<Response><Pause length="1"/><Say>')

    # 1. Exact required greeting text
    assert ("Hello, this is an AI assistant calling for South Sunflower County Hospital "
            "about a patient transfer. Please hold one moment.") in twiml
    # 2. <Say> exists
    assert "<Say>" in twiml
    # 3. <Connect> exists
    assert "<Connect>" in twiml
    # 4. <Say> occurs before <Connect>
    assert twiml.index("<Say>") < twiml.index("<Connect>")
    # 5. <Stream> exists
    assert "<Stream" in twiml
    # 6. transfer_id present in Stream parameters
    assert "TXTEST1" in twiml
    # 7. agent_id present in Stream parameters
    assert '"A1"' in twiml


def test_realtime_startup_failure_sends_apology_not_silent_hangup(monkeypatch):
    """Req 2 (positive): when _openai_connect() raises, _bridge() must call _twilio with
    an apology Url= — NOT Status=completed (silent drop). Apology TwiML must have <Say> and <Hangup/>."""
    monkeypatch.setenv("PUBLIC_HOST", "test.ngrok-free.app")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "toktest")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15550000")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")   # so has_openai() returns True

    twilio_calls = []

    async def fake_twilio(path: str, data: dict) -> dict:
        twilio_calls.append({"path": path, "data": data})
        return {"sid": "SIM_SID"}

    async def fail_connect():
        raise ConnectionRefusedError("simulated Realtime startup failure")

    def fake_openai_connect():
        return fail_connect()

    fake_ws = MagicMock()
    fake_ws.close = AsyncMock()
    bridge = Bridge(
        ws=fake_ws,
        header=H,
        transfer_id="TXTEST2",
        brief="test brief",
        stream_sid="SS1",
        call_sid="CA_LIVE_SID",
    )

    twiml_docs.clear()

    with (patch("services.sync_twilio.app.main._twilio", new=fake_twilio),
          patch("services.sync_twilio.app.main._openai_connect", new=fake_openai_connect)):
        asyncio.run(bridge._bridge())

    # Exactly one Twilio call was made
    assert len(twilio_calls) == 1, f"Expected 1 Twilio call, got {twilio_calls}"
    call = twilio_calls[0]

    # It targeted the live call SID for update, not creating a new call
    assert "CA_LIVE_SID" in call["path"]
    # It used Url= (apology TwiML), not Status=completed (silent hangup)
    assert "Url" in call["data"]
    assert "Status" not in call["data"]

    # Resolve and inspect the apology TwiML content
    doc_id = call["data"]["Url"].removeprefix("https://test.ngrok-free.app/twiml/")
    assert doc_id in twiml_docs
    apology_twiml = twiml_docs[doc_id]
    assert "<Say>" in apology_twiml
    assert "<Hangup/>" in apology_twiml


def test_mid_call_drop_does_not_send_apology(monkeypatch):
    """Req 2 (negative): plain hangup() sends Status=completed only — no apology Url=.
    Verifies the existing mid-call-drop primitive is a silent drop, not an apology."""
    monkeypatch.setenv("PUBLIC_HOST", "test.ngrok-free.app")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "toktest")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15550000")

    twilio_calls = []

    async def fake_twilio(path: str, data: dict) -> dict:
        twilio_calls.append({"path": path, "data": data})
        return {}

    fake_ws = MagicMock()
    fake_ws.close = AsyncMock()
    bridge = Bridge(ws=fake_ws, header=H, transfer_id="TXTEST3", brief="",
                    stream_sid="SS2", call_sid="CA_LIVE_SID2")

    with patch("services.sync_twilio.app.main._twilio", new=fake_twilio):
        asyncio.run(bridge.hangup())

    assert len(twilio_calls) == 1
    # Normal hangup sends Status=completed, never an apology Url=
    assert twilio_calls[0]["data"].get("Status") == "completed"
    assert "Url" not in twilio_calls[0]["data"]


@pytest.mark.parametrize("bed", [True, False])
@pytest.mark.parametrize("confirmed", [False, None, "false", "true", 1])
def test_every_report_requires_boolean_confirmation(bed, confirmed):
    async def run():
        b = gateway.Bridge(AsyncMock(), H, "T1", default_brief(H), "stream", "call")
        b.oai = AsyncMock()
        args = {"bed": bed, "ready_in_min": 10 if bed else None, "reason": None, "confirmed": confirmed}
        for _ in range(2):  # A repeated unconfirmed call must never bypass the guard.
            await b._on_tool({"name": "report_capacity", "call_id": "tool", "arguments": json.dumps(args)})
            assert b.report is None and b._emit_q.empty()
            outputs = [json.loads(c.args[0]) for c in b.oai.send.call_args_list
                       if json.loads(c.args[0])["type"] == "conversation.item.create"]
            assert json.loads(outputs[-1]["item"]["output"])["ok"] is False
        # A subsequent confirmed answer may be recorded, exactly once.
        args["confirmed"] = True
        try:
            await b._on_tool({"name": "report_capacity", "call_id": "tool", "arguments": json.dumps(args)})
            await b._on_tool({"name": "report_capacity", "call_id": "duplicate", "arguments": json.dumps(args)})
            assert b.report == args
            path, event = b._emit_q.get_nowait()
            assert path == "/events" and event["type"] == "answer_recorded"
            assert event["data"]["bed"] is bed
            assert b._emit_q.empty()
        finally:
            for task in b._tasks:
                task.cancel()
            await asyncio.gather(*b._tasks, return_exceptions=True)
    asyncio.run(run())


@pytest.mark.parametrize("arguments", ["not json", "[]", "null"])
def test_malformed_report_does_not_record_an_answer(arguments):
    async def run():
        b = gateway.Bridge(AsyncMock(), H, "T1", default_brief(H), "stream", "call")
        b.oai = AsyncMock()
        await b._on_tool({"name": "report_capacity", "call_id": "tool", "arguments": arguments})
        assert b.report is None and b._emit_q.empty()
    asyncio.run(run())


def test_connect_updates_winning_call_with_summary_before_dial(monkeypatch):
    monkeypatch.setattr(gateway.config, "has_twilio", lambda: True)
    monkeypatch.setattr(gateway, "live_calls", {("T1", "A1"): {"call_sid": "winning-call"}})
    send = AsyncMock(return_value={"sid": "winning-call"})
    monkeypatch.setattr(gateway, "_twilio", send)
    req = gateway.BridgeRequest(transfer_id="T1", agent_id="A1", summary="Summary & passcode 1234",
                                clinician="+15550101", fallback_hospital="+15550102")
    result = asyncio.run(gateway.bridge(req))
    assert result["via"] == "live_call" and send.await_count == 1
    path, data = send.call_args.args
    assert path == "Calls/winning-call.json"
    assert "Twiml" not in data
    twiml = gateway.twiml_docs[data["Url"].rsplit("/", 1)[-1]]
    assert twiml == '<Response><Say>Summary &amp; passcode 1234</Say><Dial>+15550101</Dial></Response>'


def test_connect_rejected_update_uses_configured_fallback(monkeypatch):
    monkeypatch.setattr(gateway.config, "has_twilio", lambda: True)
    monkeypatch.setattr(gateway, "live_calls", {("T1", "A1"): {"call_sid": "ended-call"}})
    response = httpx.Response(400, request=httpx.Request("POST", "https://api.twilio.com/test"))
    error = httpx.HTTPStatusError("Call no longer active", request=response.request, response=response)
    send = AsyncMock(side_effect=[error, {"sid": "fallback-call"}])
    monkeypatch.setattr(gateway, "_twilio", send)
    req = gateway.BridgeRequest(transfer_id="T1", agent_id="A1", clinician="+15550101", fallback_hospital="+15550102")
    result = asyncio.run(gateway.bridge(req))
    assert result == {"mode": "live", "sid": "fallback-call", "via": "new_call"}
    assert send.await_count == 2
    path, data = send.call_args.args
    assert path == "Calls.json" and data["To"] == req.fallback_hospital
    assert "Twiml" not in data
    assert "<Dial>+15550101</Dial>" in gateway.twiml_docs[data["Url"].rsplit("/", 1)[-1]]


def test_connect_rejected_update_without_fallback_does_not_redial(monkeypatch):
    monkeypatch.setattr(gateway.config, "has_twilio", lambda: True)
    monkeypatch.setattr(gateway, "live_calls", {("T1", "A1"): {"call_sid": "ended-call"}})
    response = httpx.Response(400, request=httpx.Request("POST", "https://api.twilio.com/test"))
    send = AsyncMock(side_effect=httpx.HTTPStatusError("Call no longer active", request=response.request, response=response))
    monkeypatch.setattr(gateway, "_twilio", send)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(gateway.bridge(gateway.BridgeRequest(transfer_id="T1", agent_id="A1", clinician="+15550101")))
    assert send.await_count == 1
