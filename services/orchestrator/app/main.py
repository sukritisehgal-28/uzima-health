"""Orchestrator: survival-window selection, bed-memory skip, swarm launch, ranking, hold and release, handoff twin."""
import asyncio
import json
import httpx
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from services.orchestrator.app.launcher import get_launcher
from services.orchestrator.app.routing import transport
from services.shared import config
from services.shared.clients import client
from services.shared.schemas import AcceptRequest, AgentHeader, AgentResult, Case, Specialty, TransferEvent, TwinRequest

app = FastAPI(title="Project Uzima orchestrator")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
DATA = json.loads((Path(__file__).resolve().parents[3] / "data" / "hospitals.json").read_text())
CENTERS = {c["id"]: c for c in DATA["centers"]}
HANDOFF_MIN = 10
MEMORY_TTL_S = 30 * 60
SWARM_TIMEOUT = int(os.getenv("SWARM_TIMEOUT_SECONDS", "90"))
TRANSFERS: dict[str, dict] = {}

QUESTION = {
    Specialty.cardiac_icu: "Do you have a cardiac ICU bed and a cath lab team available right now?",
    Specialty.stroke_thrombectomy: "Do you have a neuro ICU bed and a thrombectomy team available right now?",
    Specialty.trauma_adult: "Do you have a trauma bay and surgical team available right now?",
    Specialty.trauma_burn: "Do you have a burn ICU bed and burn team available right now?",
    Specialty.trauma_pediatric: "Do you have a pediatric trauma bay and team available right now?",
    Specialty.childbirth: "Do you have a labor and delivery bed, an obstetrician for an emergency C-section, and a NICU bed available right now?",
}


def live_phones() -> list[str]:
    """Verified demo phones that get a real call, nearest hospital first. DEMO_HOSPITAL_PHONES="+1...,+1...,+1..."."""
    raw = config.env("DEMO_HOSPITAL_PHONES") or config.env("DEMO_HOSPITAL_PHONE")
    return [p.strip() for p in raw.split(",") if p.strip()] or ["[demo phone]"]


def window_for(specialty: Specialty, window_min: int | None = None) -> dict:
    """The case's default window, or the clinician's own "care within N minutes" (10 to 120)."""
    w = dict(DATA["windows"][DATA["demo_cases"][specialty.value]["window"]])
    if window_min:
        m = max(10, min(120, int(window_min)))
        w.update(transport_budget_min=m, hard_max_min=m, label=f"Care within {m} min")
    return w


def select_centers(specialty: Specialty, memory: dict | None = None, override_outside: bool = False,
                   window_min: int | None = None) -> list[AgentHeader]:
    """Every capable center inside the window, nearest first; skips centers that said no in the last 30 min."""
    case = DATA["demo_cases"][specialty.value]
    window = window_for(specialty, window_min)
    now, picked = time.time(), []
    for cid in case["center_ids"]:
        t = transport(DATA["sending"], CENTERS[cid], window)
        if t.tier == "outside" and not override_outside:
            continue
        m = (memory or {}).get(cid)
        if m and m.get("status") == "declined" and now - m.get("ts", 0) < MEMORY_TTL_S:
            continue
        picked.append((cid, t))
    if not picked and memory:            # nothing left after memory skips: call everyone in the window again
        return select_centers(specialty, None, override_outside, window_min)
    phones = live_phones()
    headers = []
    for i, (cid, t) in enumerate(picked, start=1):
        c = CENTERS[cid]
        headers.append(AgentHeader(agent_id=f"A{i}", hospital_id=cid, hospital=c["name"], lat=c["lat"], lng=c["lng"],
                                   phone=phones[i - 1] if i <= len(phones) else "[simulated]",
                                   specialty=specialty, capability_question=QUESTION[specialty], transport=t, live=(i <= len(phones))))
    return headers


def rank(results: list[dict]) -> list[dict]:
    yes = [r for r in results if r["status"] == "available" and r.get("treatment_start_min") is not None]
    return sorted(yes, key=lambda r: (r["treatment_start_min"], min(r["transport"]["est_ground_min"], r["transport"]["est_air_min"])))


async def _tevent(tid: str, kind: str, hospital_id: str | None = None, **data) -> None:
    ev = TransferEvent(transfer_id=tid, type=kind, hospital_id=hospital_id, at=datetime.now(timezone.utc), data=data)
    async with client("collector") as c:
        await c.post("/transfer-events", json=ev.model_dump(mode="json"))


async def _results(tid: str) -> list[dict]:
    async with client("collector") as c:
        return (await c.get(f"/transfers/{tid}/results")).json()


@app.post("/transfers")
async def start_transfer(case: Case, background: BackgroundTasks):
    try:
        async with client("collector") as c:
            memory = (await c.get("/memory")).json()
    except Exception:
        memory = {}
    headers = select_centers(case.specialty, memory, window_min=case.window_min)
    tid = uuid.uuid4().hex[:10]
    TRANSFERS[tid] = {"case": case, "headers": headers, "started": time.time(), "state": "searching"}
    await _tevent(tid, "search_started", agents=[h.model_dump(mode="json") for h in headers],
                  window=window_for(case.specialty, case.window_min))
    background.add_task(get_launcher().launch, tid, headers)
    return {"transfer_id": tid, "agents": [h.model_dump(mode="json") for h in headers]}


@app.get("/transfers/{tid}")
async def transfer_status(tid: str):
    t = TRANSFERS.get(tid) or HTTPException(404)
    if isinstance(t, HTTPException):
        raise t
    if (t.get("bridge") or {}).get("mode") == "live":
        try:
            async with client("sync_twilio") as c:
                response = await c.get(f"/handoffs/{tid}", timeout=2)
                if response.status_code == 200:
                    t["bridge"] = response.json()
        except httpx.HTTPError:
            pass  # Keep the last confirmed state during a temporary outage.
    results = await _results(tid)
    elapsed = t.get("accepted_at", time.time()) - t["started"]
    ranking = rank(results)
    timeout = max(SWARM_TIMEOUT, float(config.env("LIVE_CALL_TIMEOUT_S", "300")) + 25) if any(h.live for h in t["headers"]) and config.has_twilio() else SWARM_TIMEOUT
    done = len(results) >= len(t["headers"]) or elapsed > timeout
    return {"transfer_id": tid, "state": t["state"], "elapsed_s": round(elapsed, 1), "agents": len(t["headers"]),
            "answered": len(results), "done": done, "results": results, "ranking": ranking,
            "recommendation": ranking[0] if ranking else None, "twin": t.get("twin"), "bridge": t.get("bridge"),
            "headers": [h.model_dump(mode="json") for h in t["headers"]],
            "case": t["case"].model_dump(mode="json") if t.get("case") else None}


@app.post("/transfers/{tid}/accept")
async def accept(tid: str, req: AcceptRequest):
    t = TRANSFERS.get(tid)
    if not t:
        raise HTTPException(404)
    async with t.setdefault("accept_lock", asyncio.Lock()):
        if t.get("accept_response"):
            return t["accept_response"]
        results = await _results(tid)
        ranking = rank(results)
        chosen = next((r for r in ranking if r["hospital_id"] == req.hospital_id), None) if req.hospital_id else (ranking[0] if ranking else None)
        if not chosen:
            raise HTTPException(409, "no available center to accept yet")
        insurance = None
        if config.env("STEDI_MOCK_MEMBER_ID"):
            insurance = {k: config.env(f"STEDI_MOCK_{k.upper()}") for k in ("payer_id", "member_id", "first", "last", "dob")}
        twin_req = TwinRequest(case=t["case"], accepted_hospital_id=chosen["hospital_id"], accepting_physician=req.accepting_physician,
                               transport=chosen["transport"], calls=[AgentResult(**r) for r in results], insurance_test=insurance)
        twin = t.get("pending_twin") if t.get("pending_hospital") == chosen["hospital_id"] else None
        try:
            if twin is None:
                async with client("handoff") as c:
                    response = await c.post("/twins", json=twin_req.model_dump(mode="json"))
                    response.raise_for_status()
                    twin = response.json()
                t["pending_twin"], t["pending_hospital"] = twin, chosen["hospital_id"]
        except httpx.HTTPError:
            raise HTTPException(502, "The transfer ticket could not be created. Please retry.")
        case: Case = t["case"]
        tr = chosen["transport"]
        travel = tr["est_ground_min"] if tr["recommended_mode"] == "ground" else tr["est_air_min"]
        ins = (twin.get("insurance") or {}).get("payer")
        insurance_source = (twin.get("insurance") or {}).get("source", "")
        insurance_line = ((f"Demo insurance data lists {ins}. " if "mock" in insurance_source
                           else f"Insurance checked with {ins}. ") if ins else "")
        summary = (f"This is the Uzima assistant with the referral summary. {case.age} year old {case.sex.lower()}, {case.condition}. "
                   f"Arriving by {tr['recommended_mode']} in about {travel} minutes. "
                   + insurance_line +
                   "The transfer ticket with the full record travels with the patient. Connecting you to the referring doctor now.")
        try:
            async with client("sync_twilio") as c:
                response = await c.post("/bridge", json={"transfer_id": tid, "agent_id": chosen["agent_id"], "summary": summary,
                                              "clinician": config.env("DEMO_SENDING_DOCTOR_PHONE", "[referring clinician]"),
                                              "accepting_doctor": config.env("DEMO_ACCEPTING_DOCTOR_PHONE"),
                                              "fallback_hospital": config.env("DEMO_ACCEPTING_DOCTOR_PHONE", "[accepting doctor]")})
                response.raise_for_status()
                bridge = response.json()
        except httpx.HTTPError:
            raise HTTPException(502, "Doctor connection failed. No connection is confirmed; please retry.")
        if bridge.get("mode") not in {"live", "mock"}:
            raise HTTPException(502, "The phone service did not acknowledge the connection request.")
        t["bridge"] = {"mode": bridge["mode"], "status": bridge.get("status", "initiated") if bridge["mode"] == "live" else "simulated"}
        t["state"] = "accepted"
        t["accepted_at"] = time.time()
        await _tevent(tid, "held", chosen["hospital_id"])
        for result in ranking:
            if result["hospital_id"] != chosen["hospital_id"]:
                await _tevent(tid, "released", result["hospital_id"])
        await _tevent(tid, "accepted", chosen["hospital_id"], accepting_physician=req.accepting_physician)
        t["twin"] = {"shlink": twin["shlink"], "hospital": chosen["hospital"], "insurance": twin.get("insurance"),
                     "ticket": twin.get("ticket")}
        await _tevent(tid, "twin_ready", chosen["hospital_id"], **t["twin"])
        t["accept_response"] = {"accepted": chosen["hospital"], "treatment_start_min": chosen["treatment_start_min"], "twin": t["twin"], "bridge": t["bridge"]}
        return t["accept_response"]

@app.get("/centers")
def centers():
    return {"sending": DATA["sending"], "centers": DATA["centers"], "demo_cases": DATA["demo_cases"], "windows": DATA["windows"]}


@app.get("/health")
def health():
    return {"ok": True, "integrations": config.integrations(), "centers": len(CENTERS)}
