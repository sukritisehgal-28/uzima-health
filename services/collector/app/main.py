"""Collector: receives the four call events, full results and transfer events; streams them to the dashboard;
keeps bed memory and the EMTALA log (memory, or DynamoDB write-through when AWS is on)."""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from services.collector.app.storage import make_store
from services.shared.schemas import AgentResult, CallEvent, TransferEvent

app = FastAPI(title="Project Uzima collector")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
store = make_store()
_clients: set[WebSocket] = set()


async def _broadcast(payload: dict) -> None:
    for ws in list(_clients):
        try:
            await ws.send_json(payload)
        except Exception:
            _clients.discard(ws)


@app.post("/events")
async def post_event(ev: CallEvent):
    d = ev.model_dump(mode="json")
    store.add_event(d)
    await _broadcast({"kind": "event", **d})
    return {"ok": True}


@app.post("/results")
async def post_result(result: AgentResult):
    d = result.model_dump(mode="json")
    store.add_result(d)
    await _broadcast({"kind": "result", **d})
    return {"ok": True}


@app.post("/transfer-events")
async def post_transfer_event(ev: TransferEvent):
    d = ev.model_dump(mode="json")
    store.add_transfer_event(d)
    await _broadcast({"kind": "transfer", **d})
    return {"ok": True}


@app.get("/transfers/{transfer_id}/results")
def transfer_results(transfer_id: str):
    return list(store.results.get(transfer_id, {}).values())


@app.get("/transfers/{transfer_id}/events")
def transfer_events(transfer_id: str):
    return {"calls": store.events.get(transfer_id, []), "transfer": store.transfer_events.get(transfer_id, [])}


@app.get("/memory")
def memory():
    return store.memory


@app.get("/log/{hospital_id}")
def log(hospital_id: str):
    return store.by_hospital.get(hospital_id, [])


@app.get("/health")
def health():
    return {"ok": True, "storage": store.mode, "clients": len(_clients)}


@app.websocket("/stream")
async def stream(ws: WebSocket):
    await ws.accept()
    _clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(ws)
