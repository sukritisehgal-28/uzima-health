import asyncio
import base64
import hashlib
import hmac
import json
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


@pytest.mark.parametrize("speech,value", [("10", 10), ("ten minutes", 10), ("about twenty five", 25), ("10 to 15 minutes", 15),
                                          ("between ten and fifteen", 15), ("half an hour", 30), ("an hour", 60), ("a quarter of an hour or so", 15),
                                          ("three quarters of an hour", 45), ("an hour and a half", 90),
                                          ("right now", 0), ("forty five mins", 45), ("we have two beds", 2), ("soon", None)])
def test_minutes_in_spoken_answers(speech, value):
    assert gather.minutes(speech) == value


@pytest.mark.parametrize("speech,value", [("yeah", True), ("yes we have a bed", True), ("yes but not until tomorrow", None),
                                          ("no we're full", False), ("nope", False), ("maybe", None)])
def test_bed_answers_without_a_model(speech, value):
    assert gather.literal_answer("availability", speech) == value


@pytest.mark.parametrize("speech,intent", [("hold on", "hold"), ("give me a second", "hold"), ("sorry, can you repeat that?", "repeat"),
                                           ("what?", "repeat"), ("who is this?", "question"), ("which patient", "question"),
                                           ("let me check and call you back", "callback"), ("yes", None),
                                           ("I'm not able to understand what you're asking", "clarify"),
                                           ("I don't understand", "clarify"), ("what do you mean?", "clarify"),
                                           ("sorry, I'm lost", "clarify")])
def test_what_people_say_besides_an_answer(speech, intent):
    assert gather.spoken_intent(speech) == intent


def test_hold_repeat_and_who_is_calling_then_answer(voice):
    tid, _, post, _ = voice
    held = post(0, "hold on").text
    assert "Sure, I will wait" in held and '<Pause length="10"/>' in held and "Say yes or no" in held
    assert "Of course." in post(1, "sorry, can you repeat that?").text
    who = post(2, "who is this?").text
    assert "AI assistant" in who and "South Sunflower" in who and "Say yes or no" in who
    assert "How many minutes" in post(3, "yeah we have a bed").text
    assert "ready in 15 minutes" in post(4, "10 to 15 minutes").text


def test_readback_needs_an_explicit_yes(voice):
    tid, _, post, _ = voice
    post(0, "yes")
    post(1, "ten")
    assert "Just to confirm, please say yes" in post(2, "yeah").text
    assert not results(tid)
    assert "stay on the line" in post(3, "yes").text
    assert results(tid)[0]["ready_in_min"] == 10


def test_unclear_readback_never_records_an_answer(voice):
    tid, _, post, _ = voice
    post(0, "yes")
    post(1, "ten")
    post(2, "yeah")
    post(3, "sure")
    assert "Hangup" in post(4, "I think so").text
    assert results(tid)[0]["status"] == "no_answer"


def test_call_back_request_ends_politely(voice):
    tid, _, post, _ = voice
    assert "Hangup" in post(0, "let me check with the charge nurse and call you back").text
    assert results(tid)[0]["status"] == "callback_requested"


def test_model_only_when_the_rules_cannot_tell_and_never_invents(voice, monkeypatch):
    from fastapi import FastAPI
    tid, _, post, _ = voice
    model, asked = FastAPI(), []
    @model.post("/complete")
    def complete(body: dict):
        asked.append(json.loads(body["messages"][1]["content"])["utterance"])
        assert body["output_schema"]["properties"]["intent"]["enum"]
        if "squeeze" in asked[-1]:
            return {"content": json.dumps({"intent": "answer", "bed": True, "ready_in_min": None})}
        return {"content": "not json"}                       # a broken reply is treated as unclear
    clients.register_asgi("sync_openai", model)
    monkeypatch.setattr(gather.config, "has_llm", lambda: True)
    assert "How many minutes" in post(0, "we could probably squeeze them in").text
    assert "Sorry, I did not get a clear answer" in post(1, "the usual").text
    assert "ready in 20 minutes" in post(2, "twenty").text   # plain rules answer: no model call
    assert asked == ["we could probably squeeze them in", "the usual"]


def test_unsigned_telnyx_answers_are_used_only_after_telnyx_confirms_the_call(voice, monkeypatch):
    tid, token, post, _ = voice
    monkeypatch.setenv("PHONE_PROVIDER", "telnyx")
    monkeypatch.setenv("TELNYX_ACCOUNT_SID", "acct")
    monkeypatch.setenv("TELNYX_FROM_NUMBER", "+16623002188")
    phone = gather.sessions[token]["header"].phone
    lookup = AsyncMock(side_effect=[__import__("httpx").ConnectTimeout("slow"),
                                    {"account_sid": "acct", "from": "+16623002188", "to": phone}])
    monkeypatch.setattr(gateway, "telnyx_call", lookup)
    again = post(0, "yes").text                                  # Telnyx unreachable: same question, nothing used
    assert "Say yes or no" in again and "How many minutes" not in again
    assert "How many minutes" in post(0, "yes").text             # confirmed on the retry, then pinned
    assert "ready in 10 minutes" in post(1, "ten").text and lookup.await_count == 2


def test_every_question_listens_for_speech_and_keypad_in_the_order_telnyx_accepts(voice):
    _, _, post, _ = voice
    assert '<Gather input="dtmf speech"' in post(0, "hold on").text    # "speech dtmf" makes Telnyx keypad-only


def test_telnyx_questions_name_a_speech_engine(voice, monkeypatch):
    _, _, post, _ = voice
    monkeypatch.setenv("PHONE_PROVIDER", "telnyx")
    monkeypatch.setattr(gateway.config, "has_twilio", lambda: True)
    monkeypatch.setattr(gather, "confirm_telnyx_call", AsyncMock(return_value=True))
    xml = post(0, "hold on").text
    assert 'transcriptionEngine="Deepgram"' in xml and '<Gather input="dtmf speech"' in xml


@pytest.mark.parametrize("heard,clean", [
    ("This is an automated call generated on the Telnyx platform,. Please report any abuse to abuse at telnyx.com.. Yes. We have a bed.", "Yes. We have a bed."),
    ("View at telnix.com.. Yes. We have a bed.", "Yes. We have a bed."),
    ("Yes, like 10 minutes.", "Yes, like 10 minutes.")])
def test_carrier_notice_is_not_part_of_the_answer(heard, clean):
    assert gather.clean_speech(heard) == clean


@pytest.mark.parametrize("speech,value", [("so yes we have a bed", True), ("um yeah we do", True), ("we have a bed", True),
                                          ("sorry we don't have a bed", False), ("yes but no bed", None)])
def test_more_natural_bed_answers(speech, value):
    assert gather.literal_answer("availability", speech) == value


def test_repeating_the_read_back_number_is_not_a_correction(voice):
    tid, _, post, _ = voice
    post(0, "yes")
    post(1, "ten minutes")
    assert "Just to confirm, please say yes" in post(2, "yes ten minutes").text
    assert "stay on the line" in post(3, "yes").text and results(tid)[0]["ready_in_min"] == 10
    assert gather.correction("twenty", 10) and gather.correction("no", 10) and not gather.correction("ten", 10)


def test_with_simulated_doctor_calls_a_confirmed_yes_thanks_and_hangs_up(voice, monkeypatch):
    tid, _, post, _ = voice
    monkeypatch.setenv("DOCTOR_CALLS", "simulated")
    post(0, "yes")
    post(1, "ten")
    reply = post(2, "yes").text
    assert "Thank you, your answer is confirmed" in reply and reply.endswith("<Hangup/></Response>")
    assert "stay on the line" not in reply and "<Redirect" not in reply
    assert results(tid)[0]["status"] == "available" and results(tid)[0]["ready_in_min"] == 10


def test_telnyx_lines_use_the_natural_voice_and_a_short_silence_wait(voice, monkeypatch):
    _, _, post, _ = voice
    monkeypatch.setenv("PHONE_PROVIDER", "telnyx")
    monkeypatch.setattr(gateway.config, "has_twilio", lambda: True)
    monkeypatch.setattr(gather, "confirm_telnyx_call", AsyncMock(return_value=True))
    xml = post(0, "hold on").text
    assert xml.count('<Say voice="AWS.Polly.Joanna-Neural">') == 2 and "<Say>" not in xml
    assert 'speechTimeout="1"' in xml
    monkeypatch.setenv("PHONE_PROVIDER", "twilio")
    assert gather.voiced("<Response><Say>Hi</Say></Response>") == "<Response><Say>Hi</Say></Response>"


def test_not_understanding_gets_a_plain_explanation_never_a_no(voice):
    tid, _, post, _ = voice
    first = post(0, "I don't understand").text                       # "don't" must not be read as "no"
    assert "Let me put it simply" in first and "heart attack" in first and "STEMI" not in first and "Please just say yes or no" in first
    assert "main reason" not in first
    assert "Of course. Let me put it simply" in post(1, "sorry, can you repeat that?").text   # repeats the simple version
    post(2, "yes")
    assert "For example, say ten minutes" in post(3, "I'm not able to understand what you're asking").text
    post(4, "ten")
    read = post(5, "what do you mean?").text                        # at the read-back: explain, not a correction
    assert "checking that I heard you correctly" in read and "ready in 10 minutes" in read and "correct that" not in read
    assert "Hangup" in post(6, "yes").text or "stay on the line" in post(6, "yes").text
    assert results(tid)[0]["status"] == "available" and results(tid)[0]["ready_in_min"] == 10


def test_second_unclear_answer_is_explained_in_plain_words(voice):
    _, _, post, _ = voice
    assert "Sorry, I did not get a clear answer" in post(0, "the usual").text
    second = post(1, "the usual").text
    assert "still did not get a clear answer" in second and "Let me put it simply" in second and "press 1 for yes" in second
