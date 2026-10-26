"""Emitter: every call path sends the same four events plus a full result to the collector."""
from datetime import datetime, timezone

from services.shared.clients import client
from services.shared.schemas import AgentHeader, AgentResult, CallEvent


class Emitter:
    def __init__(self, header: AgentHeader, transfer_id: str) -> None:
        self.h, self.tid = header, transfer_id

    async def event(self, event_type: str, **data) -> None:
        ev = CallEvent(type=event_type, transfer_id=self.tid, agent_id=self.h.agent_id, hospital_id=self.h.hospital_id,
                       at=datetime.now(timezone.utc), data=data)
        async with client("collector") as c:
            (await c.post("/events", json=ev.model_dump(mode="json"))).raise_for_status()

    async def result(self, r: AgentResult) -> None:
        r.transfer_id = self.tid
        async with client("collector") as c:
            (await c.post("/results", json=r.model_dump(mode="json"))).raise_for_status()
