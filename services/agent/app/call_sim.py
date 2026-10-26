"""Simulated call: weighted-random hospital answer, persona transcript, the four events, then the full result."""
import asyncio
import random
from datetime import datetime, timezone

from services.agent.app.events import Emitter
from services.agent.app.responder import respond
from services.shared import config
from services.shared.clients import client
from services.shared.schemas import AgentHeader, AgentResult, Status, TranscriptLine

LARGE = {"ummc", "baptist_memphis", "methodist_university", "uams", "baptist_little_rock", "regional_one", "nmmc_tupelo"}
HANDOFF_MIN = 10
OPENING = "Hi, this is an AI assistant from Project Uzima, calling for a referring doctor at South Sunflower County Hospital. This call is recorded."


def _now():
    return datetime.now(timezone.utc)


async def _transcript(header: AgentHeader, answer: dict) -> list[TranscriptLine]:
    try:
        async with client("sync_openai") as c:
            r = await c.post("/personas", json={"hospital": header.hospital, "question": header.capability_question, "answer": answer})
            r.raise_for_status()
            return [TranscriptLine(speaker=l["speaker"], text=l["text"], at=_now()) for l in r.json()["lines"]]
    except Exception:
        return [TranscriptLine(speaker="agent", text=f"{OPENING} {header.capability_question}", at=_now())]


async def run_sim(header: AgentHeader, emit: Emitter) -> AgentResult:
    scale = config.sim_time_scale()
    await emit.event("call_started")
    await asyncio.sleep(random.uniform(5, 45) * scale)
    forced = config.sim_a1_answer() if header.live else "random"
    if forced == "available":
        answer = {"status": "available", "ready_in_min": 10}
    elif forced == "declined":
        answer = {"status": "declined", "decline_reason": "no staffed bed"}
    else:
        answer = respond(header.specialty.value, header.hospital_id in LARGE)
    status, ready, reason = Status(answer["status"]), answer.get("ready_in_min"), answer.get("decline_reason")
    if status != Status.no_answer:
        await emit.event("call_answered")
        await emit.event("answer_recorded", bed=(status == Status.available), ready_in_min=ready, reason=reason)
    await emit.event("call_ended", outcome=status.value)
    t = header.transport
    travel = t.est_ground_min if t.recommended_mode == "ground" else t.est_air_min
    result = AgentResult(agent_id=header.agent_id, hospital_id=header.hospital_id, hospital=header.hospital, lat=header.lat, lng=header.lng,
                         status=status, ready_in_min=ready, decline_reason=reason, transport=t,
                         treatment_start_min=(max(travel, ready) + HANDOFF_MIN) if ready is not None else None,
                         transcript=await _transcript(header, answer) if status != Status.no_answer else [], answered_at=_now())
    await emit.result(result)
    return result
