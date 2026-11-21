# Ingaze Action Recommendation Engine

1. Put `ingaze_sandbox_dataset.json` and `ingaze_synthetic_analytics_snapshots.json` in `data/`; `cp .env.example .env` and set `OPENROUTER_API_KEY` / `OPENROUTER_MODELS`.
2. `pip install -r requirements.txt` and `ollama pull mistral-nemo` (run with `OLLAMA_NUM_PARALLEL=4`).
3. Self-tests: `python -m backend.selftest phase1` and `python -m backend.selftest phase2`.
4. API: `uvicorn backend.main:app --reload` · UI: `cd frontend && npm i && npm run dev` (open http://localhost:5173).
5. CLI: `python -m backend.pipeline --scenario SCENARIO_A_CLOUDNOVA_FINTECH` · submission: `python -m backend.export --all --out submission.json`.

**Demo script:** run CloudNova → show winning plan, guardrails (ambassadors deferred to Phase 3, shift rotation blocked as sector noise, compensation untouched), root causes vs symptoms, ROI. Then paste the live-tweak override
`{"snapshot": {"t0_current_snapshot": {"public_reputation": {"external_claims_gap_stars_5": 0.3, "sub_ratings_5": {"management": 3.6}}}}}`
into "Edit intake" and re-run: the readiness gate opens and ambassador actions move earlier.
