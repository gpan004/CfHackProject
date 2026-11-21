"""submission.json builder (§11). CLI: python -m backend.export --all --out submission.json"""
import argparse
import asyncio
import json
import subprocess
import sys

from .config import RUNS_DIR, ROOT, TEAM_NAME, CHOSEN_ARCHITECTURE_PARADIGM
from .ingest import scenarios, sandbox
from .schemas import PipelineResult, RunRequest


def entry(r: PipelineResult) -> dict:
    c, win = r.client, r.ranked[0]
    roots = [rc for rc in r.root_causes if rc.is_root]
    symptoms = [rc for rc in r.root_causes if not rc.is_root]
    plan_blocked = [d for sp in [win] for d in sp.decisions if d.decision in ("blocked", "deferred_beyond_plan")]
    deltas = lambda d: ", ".join(f"{k} {v:+.0%}" for k, v in list(d.items())[:3])
    nc = [rc for rc in r.root_causes if rc.refutation and rc.refutation.severity == "non_critical"]
    return {
        "scenario_code": c.scenario_code,
        "diagnosed_root_causes":
            [f"{rc.hypothesis.statement} [pillars: {', '.join(rc.hypothesis.pillars)}; scope: {rc.hypothesis.affected_scope}; "
             f"relation {rc.relation:+.2f}]" for rc in roots]
            + [f"Symptom: {rc.hypothesis.statement}" for rc in symptoms],
        "blocked_traps_and_guardrails":
            [f"{d.subject}: {d.decision} — {d.reason}" for d in r.leadership_decisions + plan_blocked]
            + [f"{n.sentence}: ignored as noise — {n.reason}" for n in c.noise],
        **{f"phase_{ph}_actions": [f"{a.action} ({a.target_scope})" for a in win.plan.actions if a.phase == ph] for ph in (1, 2, 3)},
        "matched_case_studies": [f"{t['name']} — match {t['score']:.2f} — ROI: {t['measured_roi_text']} — telemetry: {deltas(t['kpi_deltas'])}"
                                 for t in r.top_cases],
        "supporting_research_snippets": [f"{s['id']} ({s['source']}): {s['finding']}" for s in r.top_snippets],
        "strategic_focus_and_do_not_touch": c.healthy_baselines + win.plan.do_not_touch,
        "cohort_specific_strategies":
            [f"{a.action} ({a.target_scope})" for a in win.plan.actions if "company" not in a.target_scope.lower()]
            + [f"Segment {s.name}: {s.rating} stars ({s.flag})" for s in c.segments if s.flag != "normal"],
        "open_questions_and_hypotheses_for_client":
            win.plan.open_questions + [f"verify: {rc.hypothesis.statement} ({rc.refutation.reason})" for rc in nc],
    }


def latest_run(code: str) -> PipelineResult | None:
    for p in sorted(RUNS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            r = PipelineResult.model_validate_json(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if r.client.scenario_code == code:
            return r
    return None


def list_key() -> str:
    ex = sandbox().get("poc_scenario_output_format", {}).get("example_submission_structure", {})
    return next((k for k, v in ex.items() if isinstance(v, list)), "scenario_submissions") if isinstance(ex, dict) else "scenario_submissions"


def main():
    from .pipeline import run_pipeline
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--scenario", action="append", default=[])
    ap.add_argument("--fresh", action="store_true", help="always re-run instead of loading the latest run")
    ap.add_argument("--out", default="submission.json")
    a = ap.parse_args()
    codes = [s["scenario_code"] for s in scenarios()] if a.all else a.scenario
    entries = []
    for code in codes:
        r = None if a.fresh else latest_run(code)
        if r is None:
            print(f"running {code} ...")
            r = asyncio.run(run_pipeline(RunRequest(scenario_code=code), run_id=f"{code}_export"))
        entries.append(entry(r))
    sub = {"team_name": TEAM_NAME, "chosen_architecture_paradigm": CHOSEN_ARCHITECTURE_PARADIGM, list_key(): entries}
    open(a.out, "w", encoding="utf-8").write(json.dumps(sub, indent=2, ensure_ascii=False))
    print(f"wrote {a.out}")
    validator = ROOT / "starter_baseline_and_validator.py"
    if validator.exists():
        subprocess.run([sys.executable, str(validator), "--validate", a.out])


if __name__ == "__main__":
    main()
