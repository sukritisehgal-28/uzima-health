import asyncio
import time
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
from fastapi import FastAPI, Response

from services.shared import clients
from services.shared.schemas import AgentHeader, Case, Specialty
from services.orchestrator.app import main as orch


def test_live_failure_never_becomes_simulated_availability(monkeypatch):
    from services.agent.app import runner, call_live
    from services.collector.app.main import app as collector
    clients.register_asgi("collector", collector)
    monkeypatch.setattr(runner.config, "has_twilio", lambda: True)
    monkeypatch.setattr(call_live, "run_live", AsyncMock(side_effect=RuntimeError("provider failure")))
    simulate = AsyncMock()
    monkeypatch.setattr(runner, "run_sim", simulate)
    try:
        result = asyncio.run(runner.run_agent(orch.select_centers(Specialty.cardiac_icu)[0], uuid4().hex))
        assert result.status == "no_answer" and result.source == "live" and result.error
        assert result.treatment_start_min is None
        simulate.assert_not_called()
    finally:
        clients.clear()


def test_search_waits_for_live_timeout(monkeypatch):
    tid = uuid4().hex
    orch.TRANSFERS[tid] = {"headers": orch.select_centers(Specialty.cardiac_icu), "started": time.time() - 100, "state": "searching"}
    monkeypatch.setattr(orch, "_results", AsyncMock(return_value=[]))
    monkeypatch.setattr(orch.config, "has_twilio", lambda: True)
    monkeypatch.setenv("LIVE_CALL_TIMEOUT_S", "300")
    assert asyncio.run(orch.transfer_status(tid))["done"] is False
    orch.TRANSFERS.pop(tid)


def test_failed_connect_is_retryable_and_success_is_idempotent(monkeypatch):
    from services.collector.app.main import app as collector
    from services.handoff.app.main import app as handoff
    gateway = FastAPI()
    calls = []
    @gateway.post("/bridge")
    async def bridge():
        calls.append(True)
        return Response(status_code=503) if len(calls) == 1 else {"mode": "live", "sid": "demo"}
    for name, app in [("collector", collector), ("handoff", handoff), ("sync_twilio", gateway)]:
        clients.register_asgi(name, app)
    tid = uuid4().hex
    h = orch.select_centers(Specialty.cardiac_icu)[0]
    case = Case(age=62, sex="Male", specialty=h.specialty, condition="Fictional demo", onset_or_last_known_well="2026-09-26T12:00:00Z")
    result = {**h.model_dump(mode="json"), "status": "available", "ready_in_min": 10, "treatment_start_min": 45}
    orch.TRANSFERS[tid] = {"headers": [h], "case": case, "started": time.time(), "state": "searching"}
    monkeypatch.setattr(orch, "_results", AsyncMock(return_value=[result]))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=orch.app), base_url="http://orchestrator") as c:
            first = await c.post(f"/transfers/{tid}/accept", json={})
            assert first.status_code == 502
            assert orch.TRANSFERS[tid]["state"] == "searching"
            assert "twin" not in orch.TRANSFERS[tid]
            responses = await asyncio.gather(*[c.post(f"/transfers/{tid}/accept", json={}) for _ in range(2)])
            assert all(r.status_code == 200 for r in responses)
            assert responses[0].json() == responses[1].json()
            assert responses[0].json()["bridge"]["status"] == "initiated"
            assert len(calls) == 2
    try:
        asyncio.run(run())
    finally:
        clients.clear()
        orch.TRANSFERS.pop(tid)
