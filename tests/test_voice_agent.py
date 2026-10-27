import json
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from services.collector.app import main as collector
from services.orchestrator.app.main import select_centers
from services.shared import clients
from services.shared.schemas import Specialty
from services.sync_twilio.app import ai_agent, gather, main as gateway


def results(tid):
    return TestClient(collector.app).get(f"/transfers/{tid}/results").json()


@pytest.fixture
def agent(monkeypatch):
    """One agent call placed through a fake Telnyx; yields (transfer id, session token, Telnyx requests)."""
    monkeypatch.setenv("PHONE_PROVIDER", "telnyx")
    monkeypatch.setenv("VOICE_PROVIDER", "telnyx_agent")
    monkeypatch.setenv("PUBLIC_HOST", "voice.example.test")
    monkeypatch.setenv("TELNYX_APP_ID", "app-1")
    monkeypatch.setenv("TELNYX_FROM_NUMBER", "+16623002188")
    monkeypatch.setattr(gateway.config, "has_twilio", lambda: True)
    monkeypatch.setattr(ai_agent, "assistant_id", AsyncMock(return_value="assistant-1"))
    sent = []

    def telnyx(request: httpx.Request):
        sent.append(request)
        return httpx.Response(200, json={"data": {"call_sid": "v3:call-1", "status": "queued"}})

    real = httpx.AsyncClient
    monkeypatch.setattr(ai_agent.httpx, "AsyncClient", lambda **kw: real(**{"transport": httpx.MockTransport(telnyx), **kw}))
    clients.register_asgi("collector", collector.app)
    tid = uuid4().hex
    h = select_centers(Specialty.cardiac_icu)[0]
    r = TestClient(gateway.app).post("/call", json={"transfer_id": tid, "header": h.model_dump(mode="json")})
    assert r.status_code == 200 and r.json() == {"mode": "live", "sid": "v3:call-1", "voice": "agent"}
    token = next(t for t, s in ai_agent.sessions.items() if s["tid"] == tid)
    try:
        yield tid, token, sent
    finally:
        clients.clear()
        ai_agent.sessions.pop(token, None)
        gateway.live_calls.pop((tid, h.agent_id), None)


def heard(monkeypatch, read_back, desk):
    rows = [{"role": "assistant", "text": read_back, "sent_at": "2026-10-27T07:00:00Z"},
            {"role": "user", "text": desk, "sent_at": "2026-10-27T07:00:03Z"}]

    async def messages(call_id):
        ai_agent.conversations[call_id] = "conv-1"
        return rows
    monkeypatch.setattr(ai_agent, "messages", messages)


def tool(token, **answer):
    body = {"session": token, "call_control_id": "v3:call-1", **answer}
    return TestClient(gateway.app).post("/agent/answer", content=json.dumps(body),
                                        headers={"content-type": "application/json"})


def test_the_call_carries_the_case_but_never_the_token_to_the_model(agent):
    tid, token, sent = agent
    call = json.loads(sent[0].content)
    assert sent[0].url.path == "/v2/texml/ai_calls/app-1" and call["AIAssistantId"] == "assistant-1"
    variables = call["AIAssistantDynamicVariables"]
    assert variables["session_token"] == token and variables["patient"] == "a heart attack patient"
    assert "cath lab" in variables["question"] and call["StatusCallback"].endswith(f"/agent/{token}/status")
    config = ai_agent.assistant_config()
    assert "{{session_token}}" not in config["instructions"] + config["greeting"]
    record = config["tools"][0]["webhook"]
    assert record["preset_body_fields"]["session"] == "{{session_token}}"
    assert "session" not in record["body_parameters"]["properties"]


def end(token):
    TestClient(gateway.app).post(f"/agent/{token}/status", data={"CallStatus": "completed", "CallSid": "v3:call-1"})


def test_an_answer_counts_at_once_and_the_full_transcript_follows(agent, monkeypatch):
    tid, token, sent = agent
    monkeypatch.setattr(ai_agent.asyncio, "sleep", AsyncMock())
    r = tool(token, outcome="available", ready_in_min=15, agreement_words="Yeah, that's right.").json()
    assert r["recorded"] and r["then"] == "hang_up" and "confirmed" in r["say_next"]
    result = results(tid)[0]
    assert result["status"] == "available" and result["ready_in_min"] == 15 and result["source"] == "live"
    heard(monkeypatch, "So you can take the patient, ready in 15 minutes. Is that correct?", "Yeah, that's right.")
    end(token)
    result = results(tid)[0]
    assert result["status"] == "available" and [l["speaker"] for l in result["transcript"]] == ["agent", "hospital"]
    forgotten = [r for r in sent if r.method == "DELETE"]
    assert len(forgotten) == 1 and forgotten[0].url.path == "/v2/ai/conversations/conv-1"   # nothing kept at Telnyx


def test_a_quote_that_is_no_agreement_is_refused(agent, monkeypatch):
    tid, token, _ = agent
    monkeypatch.setattr(gather, "agrees", AsyncMock(return_value=False))
    r = tool(token, outcome="available", ready_in_min=15, agreement_words="No, twenty.").json()
    assert not r["recorded"] and "read the answer back again" in r["say_next"].lower()
    assert not results(tid)


def test_an_answer_the_desk_never_agreed_to_is_withdrawn_after_the_call(agent, monkeypatch):
    tid, token, _ = agent
    monkeypatch.setattr(ai_agent.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(gather, "agrees", AsyncMock(return_value=False))
    assert tool(token, outcome="available", ready_in_min=15, agreement_words="Yes.").json()["recorded"]
    heard(monkeypatch, "So you can take the patient, ready in 15 minutes. Is that right?", "No, twenty.")
    end(token)
    result = results(tid)[0]
    assert result["status"] == "no_answer" and "did not confirm" in result["error"]


def test_a_missing_minute_count_is_asked_for(agent):
    tid, token, _ = agent
    r = tool(token, outcome="available", agreement_words="yes").json()
    assert not r["recorded"] and "How many minutes" in r["say_next"]


def test_call_back_and_unknown_calls(agent, monkeypatch):
    tid, token, _ = agent
    assert tool("f" * 32, outcome="callback", agreement_words="").status_code == 403
    r = TestClient(gateway.app).post("/agent/answer", content=json.dumps(
        {"session": token, "call_control_id": "v3:someone-else", "outcome": "callback", "agreement_words": ""}),
        headers={"content-type": "application/json"})
    assert r.status_code == 403
    assert tool(token, outcome="callback", agreement_words="").json()["then"] == "hang_up"
    assert results(tid)[0]["status"] == "callback_requested"


def test_a_call_that_ends_without_an_answer_is_no_answer(agent, monkeypatch):
    tid, token, _ = agent
    monkeypatch.setattr(ai_agent, "messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(ai_agent.asyncio, "sleep", AsyncMock())
    tc = TestClient(gateway.app)
    assert tc.post(f"/agent/{token}/status", data={"CallStatus": "in-progress", "CallSid": "v3:call-1"}).status_code == 204
    tc.post(f"/agent/{token}/status", data={"CallStatus": "completed", "CallSid": "v3:call-1"})
    assert results(tid)[0]["status"] == "no_answer" and results(tid)[0]["answered_at"]
    assert token not in ai_agent.sessions


def test_if_the_agent_cannot_start_the_call_goes_out_turn_based(monkeypatch):
    monkeypatch.setenv("PHONE_PROVIDER", "telnyx")
    monkeypatch.setenv("VOICE_PROVIDER", "telnyx_agent")
    monkeypatch.setenv("PUBLIC_HOST", "voice.example.test")
    monkeypatch.setattr(gateway.config, "has_twilio", lambda: True)
    monkeypatch.setattr(ai_agent, "start", AsyncMock(side_effect=httpx.ConnectError("down")))
    send = AsyncMock(return_value={"sid": "v3:fallback"})
    monkeypatch.setattr(gateway, "_twilio", send)
    clients.register_asgi("collector", collector.app)
    h = select_centers(Specialty.cardiac_icu)[0]
    try:
        r = TestClient(gateway.app).post("/call", json={"transfer_id": uuid4().hex, "header": h.model_dump(mode="json")})
        assert r.json()["sid"] == "v3:fallback"
        assert "<Gather" in gateway.twiml_docs[send.call_args.args[1]["Url"].rsplit("/", 1)[-1]]
    finally:
        clients.clear()


def test_public_gateway_passes_agent_signatures_only_on_agent_routes(monkeypatch):
    from services.public.app import main as public
    seen = []

    class Client:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def request(self, method, url, params=None, content=None, headers=None):
            seen.append((url, headers))
            return httpx.Response(204)

    monkeypatch.setattr(public.httpx, "AsyncClient", Client)
    tc = TestClient(public.app)
    signed = {"telnyx-signature-ed25519": "sig", "telnyx-timestamp": "1"}
    assert tc.post("/agent/answer", content=b"{}", headers=signed).status_code == 204
    assert tc.post(f"/voice/{'a' * 32}/0", content=b"", headers=signed).status_code == 204
    assert tc.post("/agent/somewhere-else", content=b"{}").status_code == 404
    (agent_url, agent_headers), (voice_url, voice_headers) = seen
    assert agent_url.endswith("/agent/answer") and "telnyx-signature-ed25519" in agent_headers
    assert "telnyx-signature-ed25519" not in voice_headers
