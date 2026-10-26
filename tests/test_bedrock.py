"""Bedrock text gateway contract, credential isolation and offline fallback."""
import asyncio
import io
import json
import threading
from unittest.mock import Mock

import httpx
import pytest
from botocore.exceptions import NoCredentialsError

from services.shared import config
from services.sync_openai.app import main as gateway


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setenv("USE_BEDROCK", "1")
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "openai.gpt-oss-20b-1:0")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def client_returning(monkeypatch, text, finish_reason="stop"):
    stream = io.BytesIO(json.dumps({"choices": [{"message": {"content": text}, "finish_reason": finish_reason}]}).encode())
    client = Mock()
    client.invoke_model.return_value = {"body": stream}
    factory = Mock(return_value=client)
    monkeypatch.setattr(gateway, "_bedrock_client", factory)
    return factory, client, stream


def test_bedrock_uses_aws_model_and_preserves_json_mode(monkeypatch):
    factory, client, stream = client_returning(monkeypatch, '<reasoning>Internal model text</reasoning>{"ok":true}')
    req = gateway.CompleteRequest(messages=[{"role": "user", "content": "Return JSON."}], json_mode=True)
    assert asyncio.run(gateway.post_complete(req)) == {"mode": "live", "content": '{"ok":true}'}
    factory.assert_called_once_with("us-west-2")
    call = client.invoke_model.call_args.kwargs
    assert call["modelId"] == "openai.gpt-oss-20b-1:0"
    body = json.loads(call["body"])
    assert body["model"] == call["modelId"] and body["messages"][1:] == req.messages
    assert "response_format" not in body
    assert stream.closed
    assert config.integrations()["openai"] == "live"


def test_request_can_choose_supported_bedrock_model(monkeypatch):
    _, client, _ = client_returning(monkeypatch, "Answer")
    req = gateway.CompleteRequest(messages=[], model="openai.gpt-oss-120b-1:0")
    assert asyncio.run(gateway.complete(req)) == "Answer"
    assert client.invoke_model.call_args.kwargs["modelId"] == req.model
    assert "response_format" not in json.loads(client.invoke_model.call_args.kwargs["body"])


def test_sdk_invocation_runs_off_the_audio_event_loop(monkeypatch):
    loop_thread = threading.get_ident()
    def invoke(req):
        assert threading.get_ident() != loop_thread
        return "Answer"
    monkeypatch.setattr(gateway, "_complete_bedrock", invoke)
    assert asyncio.run(gateway.complete(gateway.CompleteRequest(messages=[]))) == "Answer"


@pytest.mark.parametrize("content", [None, "", "<reasoning>unfinished", "<reasoning>only reasoning</reasoning>"])
def test_missing_final_answer_is_rejected(content):
    with pytest.raises(ValueError):
        gateway._answer_text(content)


@pytest.mark.parametrize("content", ['{"{"lines":[]}', "[]", "null"])
def test_json_mode_rejects_malformed_or_non_object_answers(monkeypatch, content):
    client_returning(monkeypatch, content)
    with pytest.raises(ValueError):
        asyncio.run(gateway.complete(gateway.CompleteRequest(messages=[], json_mode=True)))


def test_truncated_answer_is_rejected(monkeypatch):
    client_returning(monkeypatch, "Incomplete answer", finish_reason="length")
    with pytest.raises(ValueError, match="output limit"):
        asyncio.run(gateway.complete(gateway.CompleteRequest(messages=[])))


@pytest.mark.parametrize("lines", [[], [{"speaker": "doctor", "text": "Yes"}],
                                  [{"speaker": "hospital", "text": ""}], [{"speaker": "hospital", "text": "Yes"}]])
def test_invalid_conversation_uses_template_fallback(monkeypatch, lines):
    client_returning(monkeypatch, json.dumps({"lines": lines}))
    p = gateway.PersonaRequest(hospital="Demo", question="Bed available?", answer={"status": "available", "ready_in_min": 10})
    assert asyncio.run(gateway.personas(p)) == {"mode": "fallback", "lines": gateway.template_lines(p)}


def test_direct_openai_key_does_not_enable_text_requests(monkeypatch):
    monkeypatch.setenv("USE_BEDROCK", "0")
    monkeypatch.setenv("OPENAI_API_KEY", "unused-test-value")
    factory = Mock(side_effect=AssertionError("Mock mode must not contact AWS"))
    monkeypatch.setattr(gateway, "_bedrock_client", factory)
    req = gateway.CompleteRequest(messages=[])
    assert asyncio.run(gateway.post_complete(req)) == {"mode": "mock", "content": ""}
    p = gateway.PersonaRequest(hospital="Demo", question="Bed available?", answer={"status": "available", "ready_in_min": 10})
    assert asyncio.run(gateway.personas(p)) == {"mode": "mock", "lines": gateway.template_lines(p)}
    factory.assert_not_called()
    assert gateway.health()["mode"] == "mock"


def test_missing_aws_credentials_falls_back_to_templates(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "unused-test-value")
    monkeypatch.setattr(gateway, "_bedrock_client", Mock(side_effect=NoCredentialsError()))
    p = gateway.PersonaRequest(hospital="Demo", question="Bed available?", answer={"status": "declined", "decline_reason": "full"})
    assert asyncio.run(gateway.personas(p)) == {"mode": "fallback", "lines": gateway.template_lines(p)}


def test_bedrock_personas_reach_existing_http_contract(monkeypatch):
    expected = [{"speaker": "agent", "text": f"{gateway.OPENING} Bed available?"},
                {"speaker": "hospital", "text": "Sorry, we have no bed available."}]
    generated = [{"speaker": "agent", "text": "Model changed the required disclosure."}, expected[1]]
    client_returning(monkeypatch, json.dumps({"lines": generated}))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url="http://test") as client:
            response = await client.post("/personas", json={"hospital": "Demo", "question": "Bed available?", "answer": {"status": "declined"}})
            assert response.status_code == 200
            assert response.json() == {"mode": "live", "lines": expected}
    asyncio.run(run())
