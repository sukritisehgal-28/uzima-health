"""Replay data/fixtures/events_sample.json into a running collector so the dashboard moves without a live call.

    uvicorn services.collector.app.main:app --port 8003 &
    python3 scripts/replay_fixture.py            # optional: --delay 1.5 --file data/fixtures/events_sample.json
"""
import argparse
import json
import os
import time
from pathlib import Path

import httpx

COLLECTOR = os.getenv("COLLECTOR_URL", "http://localhost:8003")


def main(path: str, delay: float) -> None:
    fx = json.loads(Path(path).read_text())
    for ev in fx["events"]:
        httpx.post(f"{COLLECTOR}/events", json=ev, timeout=5).raise_for_status()
        print("event ", ev["type"], ev["agent_id"])
        time.sleep(delay)
    for r in fx["results"]:
        httpx.post(f"{COLLECTOR}/results", json=r, timeout=5).raise_for_status()
        print("result", r["agent_id"], r["status"])


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("--file", default="data/fixtures/events_sample.json"); p.add_argument("--delay", type=float, default=1.0)
    a = p.parse_args(); main(a.file, a.delay)
