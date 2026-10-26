"""The ticket follows whichever hospital actually wins: not the nearest one, not a fixed one. One process, no keys."""
import asyncio

import httpx
import pytest

from services.shared import clients


@pytest.fixture
def apps(monkeypatch):
    monkeypatch.setenv("SIM_TIME_SCALE", "0")
    monkeypatch.setenv("SIM_A1_ANSWER", "declined")                     # the nearest hospital (Greenville) says no
    import services.agent.app.call_sim as call_sim
    import services.collector.app.main as collector
    from services.collector.app.storage import make_store
    from services.handoff.app.main import app as handoff
    from services.orchestrator.app.main import CENTERS, app as orchestrator
    from services.sync_openai.app.main import app as sync_openai
    from services.sync_twilio.app.main import app as sync_twilio
    monkeypatch.setattr(collector, "store", make_store())               # no bed memory from other tests
    monkeypatch.setattr(call_sim, "respond", lambda specialty, large: {"status": "available", "ready_in_min": 20})
    for name, a in [("collector", collector.app), ("handoff", handoff), ("sync_openai", sync_openai), ("sync_twilio", sync_twilio)]:
        clients.register_asgi(name, a)
    yield orchestrator, handoff, CENTERS
    clients.clear()


def _flow(orchestrator, handoff, pick=None):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=orchestrator), base_url="http://o") as o:
            case = {"age": 71, "sex": "Female", "specialty": "cardiac_icu", "condition": "Heart attack (STEMI)",
                    "onset_or_last_known_well": "2026-09-26T14:05:00-05:00"}
            tid = (await o.post("/transfers", json=case)).json()["transfer_id"]
            status = (await o.get(f"/transfers/{tid}")).json()
            hospital_id = pick(status["ranking"]) if pick else None
            acc = await o.post(f"/transfers/{tid}/accept", json={"hospital_id": hospital_id, "accepting_physician": "Dr. Real"})
            assert acc.status_code == 200, acc.text
            twin = (await o.get(f"/transfers/{tid}")).json()["twin"]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=handoff), base_url="http://h") as h:
            page = (await h.get(twin["ticket"]["url"].split("8004", 1)[-1])).text
        return status, twin, page
    return asyncio.run(run())


def _check(ticket, center, result, page):
    t = result["transport"]
    assert ticket["to"]["name"] == center["name"] and ticket["to"]["city"] == f"{center['city']}, {center['state']}"
    assert ticket["mode"] == t["recommended_mode"]
    assert ticket["travel_min"] == (t["est_ground_min"] if t["recommended_mode"] == "ground" else t["est_air_min"])
    assert ticket["ready_in_min"] == result["ready_in_min"] and ticket["treatment_in_min"] == result["treatment_start_min"]
    assert ticket["patient"] == "71-year-old female" and ticket["from"]["city"] == "Indianola, MS"
    assert center["city"] in page and ticket["code"] in page


def test_ticket_follows_the_recommended_winner_when_the_nearest_says_no(apps):
    orchestrator, handoff, centers = apps
    status, twin, page = _flow(orchestrator, handoff)
    winner = status["ranking"][0]
    assert winner["hospital_id"] != "delta_health"                      # Greenville declined, someone else won
    _check(twin["ticket"], centers[winner["hospital_id"]], winner, page)


def test_ticket_follows_a_clinician_picked_hospital(apps):
    orchestrator, handoff, centers = apps
    status, twin, page = _flow(orchestrator, handoff, pick=lambda ranking: ranking[-1]["hospital_id"])   # not the top choice
    chosen = status["ranking"][-1]
    assert chosen["hospital_id"] != status["ranking"][0]["hospital_id"]
    _check(twin["ticket"], centers[chosen["hospital_id"]], chosen, page)
