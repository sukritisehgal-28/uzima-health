"""Live call for A1 (Engine lane).

Option A: sync_twilio places a Twilio call whose media stream is bridged to OpenAI Realtime; the bridge emits the
four events and the final result itself. This agent only starts the call and waits for that result.
Option B (fallback): a Retell or Vapi agent posts the same events/result via webhook into the collector.
If no result arrives before LIVE_CALL_TIMEOUT_S, the call counts as no answer.
"""
import asyncio
import os

from services.agent.app.events import Emitter
from services.shared.clients import client
from services.shared.schemas import AgentHeader, AgentResult, Status


async def run_live(header: AgentHeader, emit: Emitter) -> AgentResult:
    async with client("sync_twilio") as c:
        r = await c.post("/call", json={"header": header.model_dump(mode="json"), "transfer_id": emit.tid})
        r.raise_for_status()
        if r.json().get("mode") == "mock":
            raise RuntimeError("twilio in mock mode")
    deadline = asyncio.get_running_loop().time() + float(os.getenv("LIVE_CALL_TIMEOUT_S", "120"))
    async with client("collector") as c:
        while asyncio.get_running_loop().time() < deadline:
            res = (await c.get(f"/transfers/{emit.tid}/results")).json()
            mine = [x for x in res if x["agent_id"] == header.agent_id]
            if mine:
                return AgentResult(**mine[0])
            await asyncio.sleep(1)
    result = AgentResult(agent_id=header.agent_id, hospital_id=header.hospital_id, hospital=header.hospital, lat=header.lat,
                         lng=header.lng, status=Status.no_answer, transport=header.transport, source="live",
                         error="The call timed out without a confirmed answer.")
    await emit.event("call_ended", outcome="no_answer")
    await emit.result(result)
    return result
