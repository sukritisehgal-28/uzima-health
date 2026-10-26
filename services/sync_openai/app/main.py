"""OpenAI text gateway through AWS Bedrock, with bounded concurrency and SDK retries.
USE_BEDROCK=0 keeps deterministic templates. AWS credentials come from the standard SDK chain.
The separate Twilio Realtime audio bridge is not served by this text gateway.
"""
import asyncio
import json
import os
from contextlib import closing
from functools import lru_cache
from typing import Literal

import boto3
from botocore.config import Config
from fastapi import FastAPI
from pydantic import BaseModel, Field

from services.shared import config

app = FastAPI(title="Project Uzima OpenAI gateway")
MAX_CONCURRENT = int(os.getenv("OPENAI_MAX_CONCURRENT", "5"))
_slots = asyncio.Semaphore(MAX_CONCURRENT)
OPENING = "Hi, this is an AI assistant from Project Uzima, calling for a referring doctor at South Sunflower County Hospital. This call is recorded."


class CompleteRequest(BaseModel):
    messages: list[dict]
    model: str | None = None
    json_mode: bool = False


class PersonaRequest(BaseModel):
    hospital: str
    question: str
    answer: dict


class PersonaLine(BaseModel):
    speaker: Literal["agent", "hospital"]
    text: str = Field(min_length=1)


class PersonaResponse(BaseModel):
    lines: list[PersonaLine] = Field(min_length=1)


@lru_cache(maxsize=4)
def _bedrock_client(region: str):
    # Boto3 handles profiles, temporary session credentials, roles and SigV4 signing.
    return boto3.Session().client("bedrock-runtime", region_name=region, config=Config(
        connect_timeout=5, read_timeout=30, retries={"mode": "standard", "total_max_attempts": 4}))


def _answer_text(content: str) -> str:
    # Bedrock InvokeModel may prepend GPT OSS reasoning; expose only the final answer.
    if not isinstance(content, str):
        raise ValueError("Bedrock returned no text answer")
    text = content.strip()
    if text.startswith("<reasoning>"):
        _, separator, text = text.partition("</reasoning>")
        if not separator:
            raise ValueError("Bedrock returned an unfinished reasoning block")
        text = text.strip()
    if not text:
        raise ValueError("Bedrock returned an empty answer")
    return text


def _complete_bedrock(req: CompleteRequest) -> str:
    model = req.model or config.env("BEDROCK_MODEL_ID") or "openai.gpt-oss-20b-1:0"
    messages = req.messages
    if req.json_mode:
        # Native response_format produced malformed JSON in live GPT OSS tests.
        # Request plain output and validate the object before exposing it.
        messages = [{"role": "system", "content": "Return only a valid JSON object. Do not use Markdown fences "
                     "or any text outside the JSON. Reasoning: low"}, *messages]
    body = {"model": model, "messages": messages, "max_completion_tokens": 2048, "reasoning_effort": "low"}
    region = config.env("AWS_REGION") or config.env("AWS_DEFAULT_REGION") or "us-west-2"
    response = _bedrock_client(region).invoke_model(
        modelId=model, body=json.dumps(body), contentType="application/json", accept="application/json")
    with closing(response["body"]) as stream:
        result = json.loads(stream.read())
    choice = result["choices"][0]
    if choice.get("finish_reason") == "length":
        raise ValueError("Bedrock answer exceeded the output limit")
    answer = _answer_text(choice["message"]["content"])
    if req.json_mode and not isinstance(json.loads(answer), dict):
        raise ValueError("Bedrock returned JSON that is not an object")
    return answer


async def complete(req: CompleteRequest) -> str:
    async with _slots:
        return await asyncio.to_thread(_complete_bedrock, req)


def template_lines(p: PersonaRequest) -> list[dict]:
    lines = [{"speaker": "agent", "text": f"{OPENING} {p.question}"}]
    a = p.answer
    if a.get("status") == "available":
        lines += [{"speaker": "hospital", "text": "Yes, we can take the patient."},
                  {"speaker": "agent", "text": "When can you be ready to receive?"},
                  {"speaker": "hospital", "text": f"About {a.get('ready_in_min')} minutes."}]
    elif a.get("status") == "callback_requested":
        lines += [{"speaker": "hospital", "text": "Call us back in five minutes, checking with the charge nurse."}]
    else:
        lines += [{"speaker": "hospital", "text": f"No, sorry - {a.get('decline_reason', 'no bed')}."}]
    return lines


@app.post("/complete")
async def post_complete(req: CompleteRequest):
    if not config.has_bedrock():
        return {"mode": "mock", "content": ""}
    return {"mode": "live", "content": await complete(req)}


@app.post("/personas")
async def personas(p: PersonaRequest):
    if not config.has_bedrock():
        return {"mode": "mock", "lines": template_lines(p)}
    base = template_lines(p)
    prompt = (f"Polish this fictional demo phone exchange with the transfer line at {p.hospital}. "
              "Return the same JSON structure with the same number of lines and speakers. Keep all agent lines "
              "unchanged. You may rephrase the hospital's sentences naturally, but preserve every fact and number. "
              "Do not add any facts, timing, bed answers or details. A request to call back does not mean yes or no. "
              f"Transcript: {json.dumps({'lines': base})}")
    try:
        content = await complete(CompleteRequest(messages=[{"role": "user", "content": prompt}], json_mode=True))
        result = PersonaResponse.model_validate_json(content)
        if [line.speaker for line in result.lines] != [line["speaker"] for line in base]:
            raise ValueError("Bedrock changed the conversation structure")
        for line, original in zip(result.lines, base):
            if line.speaker == "agent":
                line.text = original["text"]
        return {"mode": "live", "lines": [line.model_dump() for line in result.lines]}
    except Exception:
        return {"mode": "fallback", "lines": template_lines(p)}


@app.get("/health")
def health():
    return {"ok": True, "mode": "live" if config.has_bedrock() else "mock", "max_concurrent": MAX_CONCURRENT}
