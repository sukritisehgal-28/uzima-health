"""Whole flow in one process, no keys, no servers: start -> swarm -> rank -> accept -> twin -> manifest -> decrypt."""
import asyncio
import base64
import json

import httpx

from services.shared import clients


def test_end_to_end(monkeypatch):
    monkeypatch.setenv("SIM_TIME_SCALE", "0")
    monkeypatch.setenv("SIM_A1_ANSWER", "available")
    from services.collector.app.main import app as collector
    from services.handoff.app.main import app as handoff, decrypt_shl
    from services.orchestrator.app.main import app as orchestrator
    from services.sync_openai.app.main import app as sync_openai
    from services.sync_twilio.app.main import app as sync_twilio, outbox
    for name, a in [("collector", collector), ("handoff", handoff), ("sync_openai", sync_openai), ("sync_twilio", sync_twilio)]:
        clients.register_asgi(name, a)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=orchestrator), base_url="http://o") as o:
            case = {"age": 62, "sex": "Male", "specialty": "cardiac_icu", "condition": "STEMI, anterior",
                    "onset_or_last_known_well": "2026-09-26T14:05:00-05:00", "key_scores": {"HEART": 7}}
            r = (await o.post("/transfers", json=case)).json()
            tid, n = r["transfer_id"], len(r["agents"])
            s = (await o.get(f"/transfers/{tid}")).json()
            assert s["answered"] == n == 10 and s["done"]
            assert s["recommendation"] is not None                     # A1 (Greenville) forced to say yes
            acc = await o.post(f"/transfers/{tid}/accept", json={"accepting_physician": "Dr. Test"})
            assert acc.status_code == 200, acc.text
            twin = acc.json()["twin"]
            payload = json.loads(base64.urlsafe_b64decode(twin["shlink"].split("#shlink:/")[1] + "=="))
            twin_id = payload["url"].rsplit("/", 1)[1]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=handoff), base_url="http://h") as h:
            assert "P" not in payload.get("flag", "")                      # no passcode: the ticket's QR code is the key
            m = (await h.post(f"/manifests/{twin_id}", json={"recipient": "x"})).json()
        bundle = decrypt_shl(m["files"][0]["embedded"], payload["key"])
        assert bundle["entry"][0]["resource"]["title"] == "Project Uzima handoff twin"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=collector), base_url="http://c") as c:
            kinds = [e["type"] for e in (await c.get(f"/transfers/{tid}/events")).json()["transfer"]]
        assert kinds[0] == "search_started" and "accepted" in kinds and kinds[-1] == "twin_ready"
        assert not any(x["kind"] == "sms" for x in outbox)             # hospitals never get texts
        bridges = [x for x in outbox if x["kind"] == "bridge"]
        assert bridges and "ticket" in bridges[-1]["summary"] and "passcode" not in bridges[-1]["summary"]   # read on the call

    try:
        asyncio.run(run())
    finally:
        clients.clear()
