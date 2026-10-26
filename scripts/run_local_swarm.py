"""Fallback runner: the whole swarm as parallel workers in one process (no Kubernetes, no network needed).

    python3 scripts/run_local_swarm.py cardiac_icu
    python3 scripts/run_local_swarm.py stroke_thrombectomy --seed 7
"""
import argparse
import asyncio
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.agent.app.responder import respond            # noqa: E402
from services.orchestrator.app.main import DATA, HANDOFF_MIN, select_centers  # noqa: E402
from services.shared.schemas import Specialty               # noqa: E402

LARGE = {"ummc", "baptist_memphis", "methodist_university", "uams", "baptist_little_rock", "regional_one", "nmmc_tupelo"}


async def call(header, rng):
    await asyncio.sleep(rng.uniform(0.2, 1.5))
    ans = respond(header.specialty.value, header.hospital_id in LARGE, rng)
    t = header.transport
    travel = t.est_ground_min if t.recommended_mode == "ground" else t.est_air_min
    start = max(travel, ans["ready_in_min"]) + HANDOFF_MIN if ans["status"] == "available" else None
    return header, ans, travel, start


async def main(case_key: str, seed: int | None):
    rng = random.Random(seed)
    spec = Specialty(case_key)
    headers = select_centers(spec)
    w = DATA["windows"][DATA["demo_cases"][case_key]["window"]]
    print(f"{w['label']}\nTransport budget {w['transport_budget_min']} min, hard max {w['hard_max_min']} min. Calling {len(headers)} centers at once.\n")
    results = await asyncio.gather(*(call(h, rng) for h in headers))
    for h, ans, travel, start in results:
        note = ans.get("decline_reason") or (f"ready in {ans['ready_in_min']} min" if "ready_in_min" in ans else "")
        print(f"  {h.agent_id:>3} {h.hospital[:42]:<42} {h.transport.recommended_mode:>6} {travel:>4} min  {ans['status']:<19} {note}")
    yes = sorted([r for r in results if r[1]["status"] == "available"], key=lambda r: r[3])
    print()
    if not yes:
        print("No accepting center this round: retry callbacks, then widen to 'outside' tier with physician sign-off.")
        return
    best = yes[0]
    print(f"HOLD  {best[0].hospital} - treatment could start in ~{best[3]} min ({best[0].transport.recommended_mode}); physician-to-physician call next.")
    for r in yes[1:]:
        print(f"RELEASE {r[0].hospital}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("case", nargs="?", default="cardiac_icu"); p.add_argument("--seed", type=int)
    a = p.parse_args(); asyncio.run(main(a.case, a.seed))
