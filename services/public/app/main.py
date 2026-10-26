"""Expose only Twilio callbacks and handoff links through the demo HTTPS tunnel."""
import re

import httpx
from fastapi import FastAPI, HTTPException, Request, Response

from services.shared import config
from services.public.app.dashboard import router as dashboard_router

app = FastAPI(title="Uzima public demo gateway")
app.include_router(dashboard_router)


@app.get("/health")
def health():
    return {"ok": True, "service": "uzima-public"}


@app.api_route("/{path:path}", methods=["GET", "POST", "OPTIONS"])
async def forward(path: str, request: Request):
    service = None
    if re.fullmatch(r"twiml/[a-f0-9]{32}", path) and request.method in {"GET", "POST"}:
        service = "sync_twilio"
    elif re.fullmatch(r"voice/[a-f0-9]{32}/[0-9]+", path) and request.method == "POST":
        service = "sync_twilio"
    elif re.fullmatch(r"doctor-ready/[a-f0-9]{32}", path) and request.method == "POST":
        service = "sync_twilio"
    elif re.fullmatch(r"handoff-status/[a-f0-9]{32}/(?:conference|accepting|sending)", path) and request.method == "POST":
        service = "sync_twilio"
    elif path == "view" and request.method == "GET":
        service = "handoff"
    elif re.fullmatch(r"tickets/[A-Za-z0-9_-]+(?:\.pkpass)?", path) and request.method == "GET":
        service = "handoff"
    elif re.fullmatch(r"manifests/[A-Za-z0-9_-]+", path) and request.method in {"POST", "OPTIONS"}:
        service = "handoff"
    if service is None:
        raise HTTPException(404)
    headers = {k: v for k, v in request.headers.items() if k.lower() in
               {"content-type", "x-twilio-signature", "origin", "access-control-request-method", "access-control-request-headers"}}
    async with httpx.AsyncClient(timeout=12) as c:
        r = await c.request(request.method, f"{config.url(service)}/{path}", params=request.query_params,
                            content=await request.body(), headers=headers)
    return Response(r.content, status_code=r.status_code, headers={k: v for k, v in r.headers.items()
                    if k.lower() in {"content-type", "access-control-allow-origin", "access-control-allow-methods",
                                     "access-control-allow-headers", "content-disposition"}})
