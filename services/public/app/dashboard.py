"""Narrow dashboard access for the hosted demo."""
import re

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

from services.shared.clients import client

router = APIRouter(prefix="/dashboard")


@router.api_route("/{path:path}", methods=["GET", "POST"])
async def dashboard(path: str, request: Request):
    allowed = (request.method == "GET" and re.fullmatch(r"(?:health|centers|transfers/[a-f0-9]{10})", path)
               or request.method == "POST" and re.fullmatch(r"(?:transfers|transfers/[a-f0-9]{10}/accept)", path))
    if not allowed:
        raise HTTPException(404)
    body = await request.body()
    if len(body) > 65536:
        raise HTTPException(413, "Request too large.")
    try:
        async with client("orchestrator", timeout=45) as c:
            result = await c.request(request.method, "/" + path, content=body,
                                     headers={"content-type": "application/json"})
    except httpx.HTTPError:
        raise HTTPException(503, "The demo backend is offline. Keep the host laptop and tunnel running.")
    return Response(result.content, status_code=result.status_code,
                    headers={"content-type": result.headers.get("content-type", "application/json"), "cache-control": "no-store"})
