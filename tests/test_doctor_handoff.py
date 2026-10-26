import base64
import hashlib
import hmac
import re
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from services.sync_twilio.app import main as gateway


def test_accepting_doctor_is_dialed_then_summary_then_sending_doctor(monkeypatch):
    monkeypatch.setattr(gateway.config, "has_twilio", lambda: True)
    monkeypatch.setenv("PUBLIC_HOST", "voice.test")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "secret")
    send = AsyncMock(side_effect=[{"sid": "accepting"}, {"sid": "sending"}, {"sid": "desk"}])
    monkeypatch.setattr(gateway, "_twilio", send)
    monkeypatch.setattr(gateway, "live_calls", {("T3", "A1"): {"call_sid": "desk"}})
    tc = TestClient(gateway.app)
    r = tc.post("/bridge", json={"transfer_id": "T3", "agent_id": "A1", "summary": "Referral & summary",
                "clinician": "+15550000001", "accepting_doctor": "+15550000002"})
    assert r.status_code == 200 and r.json()["via"] == "doctor_conference"
    assert send.await_count == 1
    assert send.call_args.args[1]["To"] == "+15550000002"
    xml = gateway.twiml_docs[send.call_args.args[1]["Url"].rsplit("/", 1)[-1]]
    assert xml.index("Referral &amp; summary") < xml.index("<Redirect")
    assert "AI assistant" in xml
    token = re.search(r"doctor-ready/([a-f0-9]+)", xml).group(1)
    path = f"/doctor-ready/{token}"
    body = "https://voice.test" + path + "CallSidaccepting"
    signature = base64.b64encode(hmac.new(b"secret", body.encode(), hashlib.sha1).digest()).decode()
    assert tc.post(path, data={"CallSid": "accepting"}).status_code == 403
    response = tc.post(path, data={"CallSid": "accepting"}, headers={"X-Twilio-Signature": signature})
    assert response.status_code == 200 and "<Conference" in response.text
    assert send.await_args_list[1].args[1]["To"] == "+15550000001"
    assert send.await_args_list[2].args[0] == "Calls/desk.json"
    desk_xml = gateway.twiml_docs[send.await_args_list[2].args[1]["Url"].rsplit("/", 1)[-1]]
    assert 'endConferenceOnExit="false"' in desk_xml  # reception can hang up without disconnecting doctors
    again = tc.post(path, data={"CallSid": "accepting"}, headers={"X-Twilio-Signature": signature})
    assert again.text == response.text and send.await_count == 3


def test_signed_progress_tracks_both_doctors_and_reaches_dashboard_status(monkeypatch):
    import asyncio
    import time
    from services.shared import clients
    from services.orchestrator.app import main as orch
    from services.sync_twilio.app import doctor_handoff

    monkeypatch.setenv("PUBLIC_HOST", "voice.test")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "secret")
    monkeypatch.setattr(gateway.config, "has_twilio", lambda: True)
    send = AsyncMock(return_value={"sid": "test-call"})
    monkeypatch.setattr(gateway, "_twilio", send)
    monkeypatch.setattr(doctor_handoff, "handoffs", {})
    tc = TestClient(gateway.app)
    initial = tc.post("/bridge", json={"transfer_id": "progress-test", "accepting_doctor": "+15550000002", "clinician": "+15550000001"})
    assert initial.json()["status"] == "calling_accepting_doctor"
    token = next(iter(doctor_handoff.handoffs))
    assert send.call_args.args[1]["StatusCallback"].endswith(f"/{token}/accepting")
    assert send.call_args.args[1]["StatusCallbackEvent"] == ["initiated", "ringing", "answered", "completed"]

    def post(kind, **data):
        path = f"/handoff-status/{token}/{kind}" if kind != "ready" else f"/doctor-ready/{token}"
        body = "https://voice.test" + path + "".join(k + str(data[k]) for k in sorted(data))
        signature = base64.b64encode(hmac.new(b"secret", body.encode(), hashlib.sha1).digest()).decode()
        return tc.post(path, data=data, headers={"X-Twilio-Signature": signature})

    assert tc.post(f"/handoff-status/{token}/conference", data={"StatusCallbackEvent": "conference-end"}).status_code == 403
    response = post("ready", CallSid="test-call")
    assert 'participantLabel="accepting"' in response.text
    assert 'statusCallbackEvent="start end join leave"' in response.text
    assert send.call_args.args[1]["StatusCallback"].endswith(f"/{token}/sending")
    assert tc.get("/handoffs/progress-test").json()["status"] == "calling_sending_doctor"
    assert post("sending", CallStatus="in-progress", SequenceNumber="1").status_code == 204
    post("conference", StatusCallbackEvent="participant-join", ParticipantLabel="hospital", SequenceNumber="1")
    post("conference", StatusCallbackEvent="participant-join", ParticipantLabel="sending", SequenceNumber="3")
    assert tc.get("/handoffs/progress-test").json()["status"] == "calling_sending_doctor"
    # A later-arriving event for the other doctor must still count.
    post("conference", StatusCallbackEvent="participant-join", ParticipantLabel="accepting", SequenceNumber="2")
    assert tc.get("/handoffs/progress-test").json()["status"] == "connected"
    post("conference", StatusCallbackEvent="participant-leave", ParticipantLabel="hospital", SequenceNumber="4")
    assert tc.get("/handoffs/progress-test").json()["status"] == "connected"

    clients.register_asgi("sync_twilio", gateway.app)
    monkeypatch.setattr(orch, "_results", AsyncMock(return_value=[]))
    monkeypatch.setattr(orch, "TRANSFERS", {"progress-test": {"headers": [], "started": time.time(), "state": "accepted",
                         "bridge": initial.json(), "twin": {"hospital": "Demo hospital", "ticket": {"url": "test-ticket"}}}})
    try:
        status = asyncio.run(orch.transfer_status("progress-test"))
        assert status["bridge"]["status"] == "connected"
        assert status["twin"]["ticket"]["url"] == "test-ticket"
        post("conference", StatusCallbackEvent="conference-end", SequenceNumber="6")
        post("conference", StatusCallbackEvent="participant-join", ParticipantLabel="accepting", SequenceNumber="2")
        post("sending", CallStatus="ringing", SequenceNumber="0")
        status = asyncio.run(orch.transfer_status("progress-test"))
        assert status["bridge"]["status"] == "ended"
        assert status["bridge"]["connected_at"] and status["bridge"]["ended_at"]
        assert status["twin"]["ticket"]["url"] == "test-ticket"
        # Retrying doctor-ready after completion cannot dial anyone again.
        post("ready", CallSid="test-call")
        assert send.await_count == 2
    finally:
        clients.clear()


def test_unanswered_doctor_is_failed_and_cannot_be_redialed_by_late_ready(monkeypatch):
    from services.sync_twilio.app import doctor_handoff
    monkeypatch.setenv("PUBLIC_HOST", "voice.test")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "secret")
    monkeypatch.setattr(gateway.config, "has_twilio", lambda: True)
    monkeypatch.setattr(doctor_handoff, "handoffs", {})
    send = AsyncMock(return_value={"sid": "accepting"})
    monkeypatch.setattr(gateway, "_twilio", send)
    tc = TestClient(gateway.app)
    tc.post("/bridge", json={"transfer_id": "unanswered", "accepting_doctor": "+15550000002"})
    token = next(iter(doctor_handoff.handoffs))
    def post(path, data):
        body = "https://voice.test" + path + "".join(k + data[k] for k in sorted(data))
        signature = base64.b64encode(hmac.new(b"secret", body.encode(), hashlib.sha1).digest()).decode()
        return tc.post(path, data=data, headers={"X-Twilio-Signature": signature})
    assert post(f"/handoff-status/{token}/accepting", {"CallStatus": "no-answer", "SequenceNumber": "2"}).status_code == 204
    assert tc.get("/handoffs/unanswered").json()["status"] == "failed"
    assert "Hangup" in post(f"/doctor-ready/{token}", {"CallSid": "accepting"}).text
    assert send.await_count == 1
