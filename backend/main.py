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

app = FastAPI(title="Ingaze Prizm", lifespan=lifespan)


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


# ---------- engine v2 (evidence engine); v1 above is untouched and stays the fallback ----------
from .v2.pipeline import run_pipeline_v2, STAGES_V2          # noqa: E402
from .v2.schemas import RunStateV2, RunRequestV2, WhatIfRequest, RequestCheckRequest   # noqa: E402
from .v2 import steering as V2S, brief as V2B                 # noqa: E402

RUNS_V2: dict[str, RunStateV2] = {}


async def _run_v2(state: RunStateV2, req: RunRequestV2):
    def on_stage(name, done):
        state.status, state.stage = "running", name
        if done:
            state.stages_done.append(name)
    try:
        state.result = await run_pipeline_v2(req, on_stage=on_stage, run_id=state.run_id)
        state.status, state.stage = "done", None
    except Exception as e:  # the server never crashes
        state.status, state.error = "error", f"{type(e).__name__}: {e}"


@app.get("/api/v2/stages")
def get_stages_v2():
    return STAGES_V2


@app.post("/api/v2/runs")
async def post_run_v2(req: RunRequestV2):
    if not req.scenario_code and not req.scenario:
        raise HTTPException(400, "scenario_code or scenario is required")
    run_id = f"v2_{req.scenario_code or req.scenario.get('scenario_code', 'UNSEEN')}_{uuid.uuid4().hex[:6]}"
    RUNS_V2[run_id] = RunStateV2(run_id=run_id, status="queued")
    asyncio.create_task(_run_v2(RUNS_V2[run_id], req))
    return {"run_id": run_id}


@app.get("/api/v2/runs/{run_id}")
def get_run_v2(run_id: str):
    if run_id not in RUNS_V2:
        raise HTTPException(404, "unknown run")
    return RUNS_V2[run_id]


def _check_input(req):
    if not req.scenario_code and not req.scenario:
        raise HTTPException(400, "scenario_code or scenario is required")


@app.post("/api/v2/whatif")
def post_whatif(req: WhatIfRequest):
    """Instant, deterministic (no AI): the plan and ROI with the client's priorities vs the neutral analysis."""
    _check_input(req)
    return V2S.what_if(req)


@app.post("/api/v2/check-request")
def post_check_request(req: RequestCheckRequest):
    """Instant, deterministic (no AI): verdict on a request typed by the client, with its evidence path."""
    _check_input(req)
    if not req.text.strip():
        raise HTTPException(400, "text is required")
    return V2S.check_request(req)


@app.post("/api/v2/actions")
def post_actions(req: WhatIfRequest):
    """The 16 actions the engine knows (HR intervention catalog) and what the rules say about each for this company."""
    _check_input(req)
    return V2S.catalog_for(req)


@app.post("/api/v2/runs/{run_id}/brief")
async def post_rewrite_brief(run_id: str, audience: str = "board", retry: bool = False):
    """Brief of a finished run for another reader (same facts). A reader already written is returned at once;
    a rule-based fallback version is only re-attempted with the AI writer when retry=true."""
    st = RUNS_V2.get(run_id)
    if not st or not st.result:
        raise HTTPException(404, "unknown or unfinished run")
    if audience not in ("hr", "cfo", "board"):
        raise HTTPException(400, "audience must be hr, cfo or board")
    stored = st.result.briefs.get(audience)
    if stored is not None and (stored.writer == "llm_verified" or not retry):
        st.result.brief, st.result.audience = stored, audience
        return {"brief": stored, "audience": audience, "notes": ["already written for this reader"], "stored": True}
    b, notes = await V2B.rewrite_for(st.result, audience)
    st.result.briefs[audience] = b
    st.result.brief, st.result.audience = b, audience
    return {"brief": b, "audience": audience, "notes": notes, "stored": False}
