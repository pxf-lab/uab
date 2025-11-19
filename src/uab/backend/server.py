"""Entry point for the backend."""


import os
import signal
import threading
import time
from fastapi import FastAPI
from uab.backend.app.data_access.database import engine, Base
from uab.backend.app.api.routes import router


Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Universal Asset Browser",
    description="A cross-application asset browser for digital artists.",
    version="0.0.1",
)

print(f"Connecting to DB at {engine.url}")

app.include_router(router)

clients = {}


@app.get("/clients")
def get_clients():
    """
    Get a list of all currently registered client IDs.
    """
    return {"clients": list(clients.keys())}


@app.post("/register_client")
async def register(payload: dict):
    """Register a client."""
    cid = payload.get("client_id")
    clients[cid] = {"time": time.time()}
    return {"status": "registered", "clients": list(clients.keys())}


@app.post("/unregister_client")
async def unregister(payload: dict):
    """Unregister a client."""
    print(f"Unregistering client {payload.get('client_id')}")
    cid = payload.get("client_id")
    clients.pop(cid, None)
    if not clients:
        threading.Thread(target=_shutdown_after_time).start()
    return {"status": "ok", "remaining": list(clients.keys())}


def _shutdown_after_time(timer: float = 1.0):
    """Shutdown the server after a given time."""
    time.sleep(timer)
    os.kill(os.getpid(), signal.SIGTERM)


@app.post("/shutdown")
def shutdown():
    threading.Thread(target=_shutdown_after_time).start()
    return {"status": "shutting down"}
