"""FastAPI app: 3 endpoints (§8). Run: uvicorn backend.main:app --reload"""
import asyncio
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from . import matching
from .ingest import scenarios, track_a
from .pipeline import run_pipeline
from .schemas import RunRequest, RunState

RUNS: dict[str, RunState] = {}


@asynccontextmanager
async def lifespan(app):
    matching.build_corpus(track_a())     # Track A, graph and corpus embeddings once
    yield

app = FastAPI(title="Ingaze Action Recommendation Engine", lifespan=lifespan)


@app.get("/api/scenarios")
def get_scenarios():
    return [{"scenario_code": s["scenario_code"], "company_name": s["company_name"], "industry": s["industry"]} for s in scenarios()]


async def _run(state: RunState, req: RunRequest):
    def on_stage(name, done):
        state.status, state.stage = "running", name
        if done:
            state.stages_done.append(name)
    try:
        state.result = await run_pipeline(req, on_stage=on_stage, run_id=state.run_id)
        state.status, state.stage = "done", None
    except Exception as e:  # the server never crashes
        state.status, state.error = "error", f"{type(e).__name__}: {e}"


@app.post("/api/runs")
async def post_run(req: RunRequest):
    if not req.scenario_code and not req.scenario:
        raise HTTPException(400, "scenario_code or scenario is required")
    run_id = f"{req.scenario_code or req.scenario.get('scenario_code', 'UNSEEN')}_{uuid.uuid4().hex[:6]}"
    RUNS[run_id] = RunState(run_id=run_id, status="queued")
    asyncio.create_task(_run(RUNS[run_id], req))
    return {"run_id": run_id}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    if run_id not in RUNS:
        raise HTTPException(404, "unknown run")
    return RUNS[run_id]
