"""One agent = one hospital call. Live for A1 when Twilio keys exist; otherwise the simulated call (same events)."""
import logging

from services.agent.app.call_sim import run_sim
from services.agent.app.events import Emitter
from services.shared import config
from services.shared.schemas import AgentHeader, AgentResult, Status

log = logging.getLogger("agent")


async def run_agent(header: AgentHeader, transfer_id: str) -> AgentResult:
    emit = Emitter(header, transfer_id)
    if header.live and config.has_twilio():
        try:
            from services.agent.app.call_live import run_live
            return await run_live(header, emit)
        except Exception as e:
            log.warning("live call failed for %s: %s", header.agent_id, type(e).__name__)
            result = AgentResult(agent_id=header.agent_id, hospital_id=header.hospital_id, hospital=header.hospital,
                                 lat=header.lat, lng=header.lng, transport=header.transport, status=Status.no_answer,
                                 source="live", error="Live call failed; no hospital answer was confirmed.")
            await emit.event("call_ended", outcome="no_answer", error=result.error)
            await emit.result(result)
            return result
    return await run_sim(header, emit)
