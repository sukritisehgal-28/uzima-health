"""HTTP clients between services. Tests (and a single-process dev mode) can register ASGI apps instead of URLs."""
import httpx

from services.shared import config

_asgi: dict = {}


def register_asgi(name: str, app) -> None:
    _asgi[name] = app


def clear() -> None:
    _asgi.clear()


def client(name: str, timeout: float = 30.0) -> httpx.AsyncClient:
    if name in _asgi:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=_asgi[name]), base_url=f"http://{name}", timeout=timeout)
    return httpx.AsyncClient(base_url=config.url(name), timeout=timeout)
