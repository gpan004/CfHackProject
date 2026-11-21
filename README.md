# Ingaze Prizm

1. Put `ingaze_sandbox_dataset.json` and `ingaze_synthetic_analytics_snapshots.json` in `data/`; `cp .env.example .env` and set `OPENROUTER_API_KEY` / `OPENROUTER_MODELS`.
2. `pip install -r requirements.txt` and `ollama pull mistral-nemo` (run with `OLLAMA_NUM_PARALLEL=4`).
3. Self-tests: `python -m backend.selftest phase1` and `python -m backend.selftest phase2`.
4. API: `uvicorn backend.main:app --reload` · UI: `cd frontend && npm i && npm run dev` (open http://localhost:5173).
5. CLI: `python -m backend.pipeline --scenario SCENARIO_A_CLOUDNOVA_FINTECH` · submission: `python -m backend.export --all --out submission.json`.

### Engine v2 (evidence engine, branch `engine-v2`)
Knowledge-graph tools decide, agents explain, critics check. v1 stays available as the fallback (toggle in the UI).
- Graph: `data/kg_facts.json` (every cause/effect/threshold link has a verbatim source quote, validated at startup) + `backend/v2/kg.py`.
- 10 deterministic tools: `backend/v2/tools.py`. Agents, plan critic and jury critic: `backend/v2/agents.py`. Readable brief: `backend/v2/brief.py`.
- Same data -> same answer: temperature 0 + seed, model-independent cache, stability ledger in `runs/v2/ledger.json`.
- CLI: `python -m backend.v2.pipeline --scenario SCENARIO_A_CLOUDNOVA_FINTECH` (`--fresh` ignores the cache). Tests: `python -m backend.v2.selftest`.
- Colab down? `$env:V2_LOCAL_TIER="remote"` routes the local roles to OpenRouter.
- Tailoring: priorities per pillar (Less / Normal / More), instant what-if (`POST /api/v2/whatif`), request checker
  (`POST /api/v2/check-request`), reader of the brief (HR Manager / CFO / Board) with `--audience`, and PDF download in
  the UI. CLI: `python -m backend.v2.pipeline --scenario SCENARIO_A_CLOUDNOVA_FINTECH --focus retention=more,advocacy=less --audience cfo`.
- If the AI models are unavailable (e.g. daily quota), every agent degrades to the rule-based result instead of failing.

**Demo script:** run CloudNova → show winning plan, guardrails (ambassadors deferred to Phase 3, shift rotation blocked as sector noise, compensation untouched), root causes vs symptoms, ROI. Then paste the live-tweak override
`{"snapshot": {"t0_current_snapshot": {"public_reputation": {"external_claims_gap_stars_5": 0.3, "sub_ratings_5": {"management": 3.6}}}}}`
into "Edit intake" and re-run: the readiness gate opens and ambassador actions move earlier.
