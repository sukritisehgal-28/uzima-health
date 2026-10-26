import asyncio
import base64
import hashlib
import hmac
import re
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from services.collector.app import main as collector
from services.orchestrator.app.main import select_centers
from services.shared import clients
from services.shared.schemas import Specialty
from services.sync_twilio.app import gather, main as gateway


@pytest.fixture
def voice(monkeypatch):
    monkeypatch.setenv("VOICE_PROVIDER", "bedrock_gather")
    monkeypatch.setenv("PUBLIC_HOST", "voice.example.test")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-secret")
    monkeypatch.setenv("USE_BEDROCK", "0")
    monkeypatch.setattr(gateway.config, "has_twilio", lambda: True)
    send = AsyncMock(return_value={"sid": "CA-demo"})
    monkeypatch.setattr(gateway, "_twilio", send)
    clients.register_asgi("collector", collector.app)
    tc = TestClient(gateway.app)
    tid = uuid4().hex
    h = select_centers(Specialty.cardiac_icu)[0]
    r = tc.post("/call", json={"transfer_id": tid, "header": h.model_dump(mode="json")})
    assert r.status_code == 200
    xml = gateway.twiml_docs[send.call_args.args[1]["Url"].rsplit("/", 1)[-1]]
    assert "AI assistant" in xml and "<Gather" in xml and "<Stream" not in xml
    assert xml.startswith('<Response><Pause length="1"/><Gather')
    token = re.search(r"/voice/([a-f0-9]+)/0", xml).group(1)
    def post(turn, text, signature=True):
        path = f"/voice/{token}/{turn}"
        params = {"SpeechResult": text, "CallSid": "CA-demo"}
        data = f"https://voice.example.test{path}" + "".join(k + params[k] for k in sorted(params))
        sig = base64.b64encode(hmac.new(b"test-secret", data.encode(), hashlib.sha1).digest()).decode()
        return tc.post(path, data=params, headers={"X-Twilio-Signature": sig if signature else "invalid"})
    try:
        yield tid, token, post, send
    finally:
        clients.clear()
        gather.sessions.pop(token, None)
        gateway.live_calls.pop((tid, h.agent_id), None)


def results(tid):
    return TestClient(collector.app).get(f"/transfers/{tid}/results").json()


def test_speech_readback_confirmation_collector_and_connect(voice):
    tid, token, post, send = voice
    answer = post(0, "yes").text
    assert "How many minutes" in answer
    assert '<Pause length="1"' not in answer
    assert "ready in 10 minutes" in post(1, "ten minutes").text
    assert not results(tid)
    assert "stay on the line" in post(2, "yes").text
    recorded = results(tid)
    assert len(recorded) == 1
    assert recorded[0]["ready_in_min"] == 10 and recorded[0]["source"] == "live"
    assert "stay on the line" in post(2, "yes").text  # retry is cached, no second result
    assert len(results(tid)) == 1
    bridge = TestClient(gateway.app).post("/bridge", json={"transfer_id": tid, "agent_id": "A1",
                        "summary": "Clinical summary", "clinician": "+15550000001"})
    assert bridge.json()["via"] == "live_call"
    twiml = gateway.twiml_docs[send.call_args.args[1]["Url"].rsplit("/", 1)[-1]]
    assert twiml.index("Clinical summary") < twiml.index("<Dial>")


def test_correction_never_confirms_stale_ready_time(voice):
    tid, _, post, _ = voice
    post(0, "yes")
    post(1, "ten minutes")
    assert "correct that" in post(2, "yes but twenty minutes").text
    assert not results(tid)
    post(3, "yes")
    post(4, "twenty minutes")
    post(5, "correct")
    assert results(tid)[0]["ready_in_min"] == 20


def test_decline_requires_readback_and_confirmation(voice):
    tid, _, post, _ = voice
    post(0, "no")
    assert "no staffed bed" in post(1, "no staffed bed").text
    assert not results(tid)
    assert "Hangup" in post(2, "yes").text
    assert results(tid)[0]["status"] == "declined"


def test_silence_is_no_answer_and_forged_callback_is_rejected(voice):
    tid, _, post, _ = voice
    assert post(0, "yes", signature=False).status_code == 403
    post(0, "")
    post(1, "")
    assert "Hangup" in post(2, "").text
    assert results(tid)[0]["status"] == "no_answer"


@pytest.mark.parametrize("speech", ["yes but no bed", "maybe", "yes in thirty instead", "", "not correct"])
def test_qualified_answers_are_not_confirmation(speech):
    assert not gather.confirmation(speech)


def test_public_gateway_does_not_expose_dial_or_transfer_endpoints():
    from services.public.app.main import app
    tc = TestClient(app)
    for path in ["/call", "/bridge", "/transfers", "/outbox", "/twins"]:
        assert tc.post(path, json={}).status_code == 404


def test_public_gateway_forwards_signed_handoff_callbacks_only(monkeypatch):
    import httpx
    from services.public.app import main as public
    seen = []
    original_client = httpx.AsyncClient
    def receive(request):
        seen.append(request)
        return httpx.Response(204)
    monkeypatch.setattr(public.httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(receive), **kwargs))
    tc = TestClient(public.app)
    path = "/handoff-status/" + "a" * 32 + "/conference"
    assert tc.post(path, data={"StatusCallbackEvent": "conference-end"}, headers={"X-Twilio-Signature": "signed"}).status_code == 204
    assert seen[0].headers["X-Twilio-Signature"] == "signed"
    assert seen[0].content == b"StatusCallbackEvent=conference-end"
    assert tc.get(path).status_code == 404
    assert tc.get("/handoffs/private-transfer").status_code == 404
