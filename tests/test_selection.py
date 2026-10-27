import time

from services.orchestrator.app.main import CENTERS, rank, select_centers
from services.shared.schemas import Specialty


def test_every_case_has_centers_and_one_live_agent():
    for s in Specialty:
        hs = select_centers(s)
        assert hs, s
        assert [h.live for h in hs].count(True) == 1 and hs[0].live


def test_capabilities_match_the_case():
    for h in select_centers(Specialty.stroke_thrombectomy):
        assert CENTERS[h.hospital_id]["capabilities"]["thrombectomy"]["value"] is True
    for h in select_centers(Specialty.cardiac_icu):
        assert CENTERS[h.hospital_id]["capabilities"]["cardiac_icu"]["value"] is True
    assert "delta_health" not in {h.hospital_id for h in select_centers(Specialty.stroke_thrombectomy)}


def test_nothing_outside_the_window_by_default():
    for s in Specialty:
        assert all(h.transport.tier != "outside" for h in select_centers(s))


def test_bed_memory_skips_recent_declines():
    mem = {"ummc": {"status": "declined", "ts": time.time()}}
    ids = {h.hospital_id for h in select_centers(Specialty.cardiac_icu, mem)}
    assert "ummc" not in ids and "delta_health" in ids


def test_rank_orders_by_treatment_start():
    t = {"est_ground_min": 10, "est_air_min": 10}
    r = rank([{"status": "available", "treatment_start_min": 90, "transport": t},
              {"status": "declined", "treatment_start_min": None, "transport": t},
              {"status": "available", "treatment_start_min": 52, "transport": t}])
    assert [x["treatment_start_min"] for x in r] == [52, 90]


def test_clinician_window_limits_the_zone():
    wide = select_centers(Specialty.cardiac_icu)
    narrow = select_centers(Specialty.cardiac_icu, window_min=50)
    assert 0 < len(narrow) < len(wide)
    assert all(min(h.transport.est_ground_min, h.transport.est_air_min) <= 50 for h in narrow)


def test_several_live_phones(monkeypatch):
    monkeypatch.setenv("DEMO_HOSPITAL_PHONES", "+15550000001,+15550000002,+15550000003")
    hs = select_centers(Specialty.cardiac_icu)
    assert [h.live for h in hs[:4]] == [True, True, True, False]
    assert hs[1].phone == "+15550000002" and hs[3].phone == "[simulated]"


def test_childbirth_only_calls_verified_birthing_hospitals_with_a_nicu():
    import json
    from pathlib import Path
    centers = {c["id"]: c for c in json.loads((Path(__file__).resolve().parents[1] / "data" / "hospitals.json").read_text())["centers"]}
    hs = select_centers(Specialty.childbirth)
    ids = {h.hospital_id for h in hs}
    assert hs and all(centers[i]["capabilities"]["childbirth"]["value"] and centers[i]["capabilities"]["childbirth"]["source"] for i in ids)
    # children's hospitals don't deliver; these adult hospitals don't deliver or have no NICU (checked, see each capability note)
    assert not ids & {"le_bonheur", "arkansas_childrens", "methodist_university", "baptist_memphis", "chi_st_vincent", "merit_central"}
    assert "NICU" in hs[0].capability_question


def test_visitor_number_is_checked_and_limited(monkeypatch):
    from services.orchestrator.app import main as orch
    monkeypatch.setattr(orch, "VISITOR_CALLS", {})
    monkeypatch.setenv("VISITOR_CALLS_PER_DAY", "3")
    monkeypatch.setenv("VISITOR_CALLS_PER_NUMBER", "2")
    for bad in ["", "12345", "+44 20 7946 0958", "(900) 555-0123", "+1 123 555 0123"]:
        assert orch.visitor_phone(bad) == (None, "invalid")
    assert orch.visitor_phone("(662) 555-0123") == ("+16625550123", None)
    assert orch.visitor_phone("+1 662-555-0123") == ("+16625550123", None)
    assert orch.visitor_phone("662.555.0123") == (None, "limit")       # two calls per number a day
    assert orch.visitor_phone("601 555 0199") == ("+16015550199", None)
    assert orch.visitor_phone("901 555 0100") == (None, "limit")       # daily total reached
    assert "6625550123" not in str(orch.VISITOR_CALLS)                 # counted by hash only
    monkeypatch.setattr(orch, "VISITOR_CALLS", {})
    monkeypatch.setenv("VISITOR_CALLS_ALLOW", "+1 (662) 555-0123")     # e.g. only the trial's verified phone
    assert orch.visitor_phone("601 555 0199") == (None, "unavailable")
    assert orch.visitor_phone("662-555-0123") == ("+16625550123", None)


def test_only_the_visitor_number_rings_and_it_stays_private(monkeypatch):
    from services.orchestrator.app.main import public_header
    monkeypatch.setenv("DEMO_HOSPITAL_PHONES", "+15550000001")
    visitor = select_centers(Specialty.cardiac_icu, phones=["+16625550123"])
    assert visitor[0].live and visitor[0].phone == "+16625550123" and not any(h.live for h in visitor[1:])
    assert public_header(visitor[0])["phone"] == "[private]"
    nobody = select_centers(Specialty.cardiac_icu, phones=[])
    assert nobody and not any(h.live for h in nobody) and nobody[0].phone == "[simulated]"
    assert select_centers(Specialty.cardiac_icu)[0].phone == "+15550000001"   # default: configured demo phones


def test_simulated_doctor_call_steps_through_the_handoff(monkeypatch):
    from services.orchestrator.app.main import simulated_handoff
    monkeypatch.setenv("SIM_TIME_SCALE", "1")
    assert [simulated_handoff(s) for s in (0, 6, 10, 30)] == [
        "calling_accepting_doctor", "calling_sending_doctor", "connected", "ended"]
    monkeypatch.setenv("SIM_TIME_SCALE", "0")
    assert simulated_handoff(0) == "ended"


def test_public_demo_always_has_one_simulated_yes(monkeypatch):
    import asyncio
    from fastapi.testclient import TestClient
    from services.agent.app import call_sim
    from services.collector.app import main as collector
    from services.orchestrator.app import main as orch
    from services.shared import clients
    clients.register_asgi("collector", collector.app)
    monkeypatch.setenv("VISITOR_CALLS", "1")
    monkeypatch.setenv("SIM_TIME_SCALE", "0")
    launched = []
    class Launcher:
        async def launch(self, tid, headers):
            launched.extend(headers)
    monkeypatch.setattr(orch, "get_launcher", lambda: Launcher())
    r = TestClient(orch.app).post("/transfers", json={"age": 62, "sex": "Male", "specialty": "cardiac_icu", "condition": "STEMI",
                                                      "onset_or_last_known_well": "2026-10-27T00:00:00Z", "key_scores": {}})
    assert r.status_code == 200 and all("sure_yes" not in a for a in r.json()["agents"])   # not shown to the dashboard
    sure = [h for h in launched if h.sure_yes]
    assert len(sure) == 1 and not sure[0].live
    class Emit:
        async def event(self, *a, **k): pass
        async def result(self, r): self.r = r
    for _ in range(20):                                  # the simulated answer is random, except for this hospital
        e = Emit()
        assert asyncio.run(call_sim.run_sim(sure[0], e)).status.value == "available"
    monkeypatch.setenv("VISITOR_CALLS", "0")
    launched.clear()
    TestClient(orch.app).post("/transfers", json={"age": 62, "sex": "Male", "specialty": "cardiac_icu", "condition": "STEMI",
                                                 "onset_or_last_known_well": "2026-10-27T00:00:00Z", "key_scores": {}})
    assert launched and not any(h.sure_yes for h in launched)   # the team's own setup keeps fully random answers
    clients.clear()
