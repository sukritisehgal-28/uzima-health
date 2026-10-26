"""Run the existing demo services together on one Cloud Run instance."""
import json
import os
import signal
import subprocess
import sys
import time
from urllib.request import urlopen

INTERNAL = [
    ("collector", 8003), ("handoff", 8004), ("sync_openai", 8001),
    ("sync_twilio", 8002), ("orchestrator", 8000),
]


def runtime_environment():
    env = os.environ.copy()
    private = json.loads(env.pop("UZIMA_RUNTIME_JSON", "{}"))
    # Explicit Cloud Run settings override the secret's integration defaults.
    return {**private, **env}


def main():
    env = runtime_environment()
    processes = []
    def stop(*_):
        for process in processes:
            if process.poll() is None:
                process.terminate()
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    def start(name, port, host="127.0.0.1"):
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", f"services.{name}.app.main:app",
                                    "--host", host, "--port", str(port), "--log-level", "warning"], env=env)
        processes.append(process)
    try:
        for name, port in INTERNAL:
            start(name, port)
        deadline = time.monotonic() + 90
        pending = {port for _, port in INTERNAL}
        while pending:
            if any(process.poll() is not None for process in processes):
                raise RuntimeError("A backend service exited during startup")
            if time.monotonic() > deadline:
                raise RuntimeError("Backend startup timed out")
            for port in list(pending):
                try:
                    with urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                        if response.status == 200:
                            pending.remove(port)
                except OSError:
                    pass
            if pending:
                time.sleep(0.2)
        start("public", int(env.get("PORT", "8080")), "0.0.0.0")
        print("Uzima backend ready", flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(1)
        raise RuntimeError("A backend service exited; restarting the instance")
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    main()
