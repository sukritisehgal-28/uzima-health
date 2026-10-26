"""Read-only demo checks. Never starts a transfer or dials a phone."""
import json
import shlex
import sys
from pathlib import Path

import httpx


def main():
    settings = {}
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            words = shlex.split(line, comments=True)
            if words and "=" in words[0]:
                key, value = words[0].split("=", 1)
                settings[key] = value
    failures = []
    for service, port in [("orchestrator", 8000), ("Bedrock text", 8001), ("voice", 8002), ("collector", 8003),
                           ("handoff", 8004), ("public gateway", 8005)]:
        try:
            r = httpx.get(f"http://localhost:{port}/health", timeout=5)
            r.raise_for_status()
            if not r.json().get("ok"):
                raise ValueError("Service is not healthy")
            print(f"PASS {service}")
            if service == "voice":
                print(f"     provider={r.json().get('voice_provider')}; phone mode={r.json().get('mode')}")
        except Exception as e:
            failures.append(service)
            print(f"FAIL {service}: {type(e).__name__}")
    public = settings.get("HANDOFF_PUBLIC_URL", "")
    if public.startswith("https://"):
        try:
            for path in ["/health", "/view"]:
                httpx.get(public + path, timeout=15).raise_for_status()
            assert httpx.post(public + "/call", json={}, timeout=15).status_code == 404
            print("PASS public HTTPS callbacks and record viewer; dial endpoint is private")
        except Exception as e:
            failures.append("public HTTPS")
            print(f"FAIL public HTTPS: {type(e).__name__}")
    else:
        failures.append("public HTTPS")
        print("FAIL public HTTPS: configure HANDOFF_PUBLIC_URL and PUBLIC_HOST")
    try:
        r = httpx.post("http://localhost:8001/complete", json={"json_mode": True, "messages": [
            {"role": "user", "content": 'Return exactly this JSON object: {"ready":true}'}]}, timeout=15)
        r.raise_for_status()
        assert r.json()["mode"] == "live" and json.loads(r.json()["content"])["ready"] is True
        print("PASS actual Bedrock inference")
    except Exception as e:
        failures.append("Bedrock inference")
        print(f"FAIL Bedrock inference: {type(e).__name__}")
    print("Phone speech, ringing and two-way audio still require the two-person rehearsal.")
    return bool(failures)


if __name__ == "__main__":
    sys.exit(main())
