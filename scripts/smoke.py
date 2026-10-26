"""Smoke test against running services (make dev): start a transfer, wait for answers, accept, print the twin link.

    python3 scripts/smoke.py              # heart attack
    python3 scripts/smoke.py stroke_thrombectomy
"""
import sys
import time

import httpx

O = "http://localhost:8000"
args = [a for a in sys.argv[1:] if a != "--live"]
spec = args[0] if args else "cardiac_icu"
case = {"age": 62, "sex": "Male", "specialty": spec, "condition": "demo case", "onset_or_last_known_well": "2026-09-26T14:05:00-05:00"}
health = httpx.get(f"{O}/health").json()["integrations"]
print("health:", health)
if health.get("twilio") == "live" and "--live" not in sys.argv:
    sys.exit("Live phones are enabled. Use --live for an intentional phone rehearsal, or TWILIO_ENABLED=0 for simulation.")
r = httpx.post(f"{O}/transfers", json=case).json()
tid = r["transfer_id"]
print(f"transfer {tid}: calling {len(r['agents'])} centers")
while True:
    s = httpx.get(f"{O}/transfers/{tid}").json()
    print(f"  {s['elapsed_s']:>5}s  answered {s['answered']}/{s['agents']}", end="\r")
    if s["done"]:
        break
    time.sleep(1)
print()
for x in s["results"]:
    print(f"  {x['agent_id']:>3} {x['hospital'][:40]:<40} {x['status']:<19} {x.get('decline_reason') or x.get('ready_in_min') or ''}")
if not s["recommendation"]:
    sys.exit("no yes this round (try again, or set SIM_A1_ANSWER=available)")
response = httpx.post(f"{O}/transfers/{tid}/accept", json={"accepting_physician": "Dr. Demo"}, timeout=60)
response.raise_for_status()
a = response.json()
print(f"accepted: {a['accepted']} · treatment in ~{a['treatment_start_min']} min")
print("handoff created; bridge:", a.get("bridge", {}).get("status", "unknown"))
print("ticket:", (a["twin"].get("ticket") or {}).get("url", "not available"))
