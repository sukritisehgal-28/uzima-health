import httpx
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from services.public.app.main import app
from services.shared import clients


def test_hosted_api_is_public_and_only_forwards_dashboard_routes():
    origin = FastAPI()
    seen = []
    @origin.api_route("/{path:path}", methods=["GET", "POST"])
    async def receive(path: str, request: Request):
        seen.append((path, request.method, await request.body()))
        return {"ok": True}
    clients.register_asgi("orchestrator", origin)
    tc = TestClient(app)
    try:
        for path in ["health", "centers", "transfers/abcdef1234"]:
            response = tc.get("/dashboard/" + path)
            assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        for path in ["transfers", "transfers/abcdef1234/accept"]:
            assert tc.post("/dashboard/" + path, json={"demo": True}).status_code == 200
            assert seen[-1][1:] == ("POST", b'{"demo":true}')
        for path in ["call", "bridge", "outbox", "results", "twins", "transfers/not-a-transfer"]:
            assert tc.post("/dashboard/" + path, json={}).status_code == 404
        assert tc.post("/dashboard/transfers", content=b'x' * 65537).status_code == 413
    finally:
        clients.clear()


def test_hosted_api_returns_clear_failure_when_backend_is_offline(monkeypatch):
    from services.public.app import dashboard
    def offline(*args, **kwargs):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(dashboard, "client", offline)
    response = TestClient(app).get("/dashboard/health")
    assert response.status_code == 503 and "offline" in response.text
