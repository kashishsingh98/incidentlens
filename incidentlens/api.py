"""Local-only demo API. A single operation gate keeps the shared lab coherent."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from incidentlens.investigator import investigate
from incidentlens.store import baseline, change_index, initialize, latest, metrics, read_events

STATIC = Path(__file__).parent / "static"
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    await asyncio.to_thread(initialize)
    app.state.gate = asyncio.Lock()
    yield


app = FastAPI(title="IncidentLens", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def local_boundary(request: Request, call_next):
    # Local lab only. Prevent browser DNS rebinding and cross-origin mutation requests.
    host = request.url.hostname
    if host not in {"127.0.0.1", "localhost", "::1", "testserver"}:
        return JSONResponse({"detail": "Localhost access only"}, status_code=403)
    origin = request.headers.get("origin")
    if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
        return JSONResponse({"detail": "Cross-origin access denied"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; frame-ancestors 'none'"
    )
    return response


@app.get("/")
def home():
    return FileResponse(STATIC / "index.html")


@app.get("/api/state")
def state():
    experiment = latest()
    return {
        "experiment_id": experiment,
        "llm_available": bool(os.environ.get("OPENAI_API_KEY")),
        "metrics": metrics(experiment) if experiment else None,
        "events": read_events(experiment, "deployment") if experiment else [],
    }


class ExperimentRequest(BaseModel):
    experiment_id: str


class InvestigationRequest(ExperimentRequest):
    mode: Literal["rules", "llm"] = "rules"


@asynccontextmanager
async def operation():
    if app.state.gate.locked():
        raise HTTPException(409, "Another lab operation is in progress. Try again shortly.")
    async with app.state.gate:
        yield


def require_latest(experiment: str):
    if experiment != latest():
        raise HTTPException(409, "This experiment is no longer active. Refresh the page.")


@app.post("/api/lab/baseline")
async def start_baseline():
    async with operation():
        return await asyncio.to_thread(baseline)


@app.post("/api/lab/incident")
async def trigger_incident(body: ExperimentRequest):
    async with operation():
        require_latest(body.experiment_id)
        try:
            return await asyncio.to_thread(change_index, body.experiment_id, restore=False)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc


@app.post("/api/lab/recover")
async def recover(body: ExperimentRequest):
    async with operation():
        require_latest(body.experiment_id)
        try:
            return await asyncio.to_thread(change_index, body.experiment_id, restore=True)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc


@app.post("/api/investigate")
async def run_investigation(body: InvestigationRequest):
    async with operation():
        require_latest(body.experiment_id)
        try:
            # Bounds both startup and the optional model's entire tool loop.
            return await asyncio.wait_for(investigate(body.experiment_id, body.mode), timeout=180)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(504, "Investigation exceeded the 180-second deadline") from exc
        except Exception as exc:
            logger.exception("Investigation failed")
            raise HTTPException(
                502,
                "Investigation failed. Check server logs; no report was fabricated.",
            ) from exc


@app.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics():
    experiment = latest()
    lines = [
        "# HELP incidentlens_query_p95_ms Measured local query p95 in milliseconds.",
        "# TYPE incidentlens_query_p95_ms gauge",
    ]
    if experiment:
        for phase, values in metrics(experiment)["phases"].items():
            lines.append(f'incidentlens_query_p95_ms{{phase="{phase}"}} {values["p95_ms"]}')
    return "\n".join(lines) + "\n"
