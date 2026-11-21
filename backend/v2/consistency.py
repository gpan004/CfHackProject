"""Stability check: same question -> same answer.

fingerprint = hash of the normalised input (client profile) + knowledge-graph version + engine version + prompts.
signature   = hash of the DECISIONS (problems, roles, winning actions and phases, leadership verdicts, rounded ROI).
A ledger (runs_v2/ledger.json) remembers the signature per fingerprint, so every run reports whether it gave the same
answer as before, and lists exactly what changed if it did not.
"""
import hashlib
import json

from ..config import RUNS_DIR
from . import prompts
from .kg import facts
from .schemas import Stability

ENGINE_VERSION = "v2.0"
LEDGER = RUNS_DIR / "v2" / "ledger.json"


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]


def fingerprint(client, focus: dict | None = None) -> str:
    """The client's priorities are part of the question; the reader of the brief is not (it never changes decisions)."""
    prompt_text = "".join(getattr(prompts, n) for n in dir(prompts) if n.isupper() and isinstance(getattr(prompts, n), str))
    return _h({"client": client.model_dump(), "kg": facts()["version"], "engine": ENGINE_VERSION, "prompts": _h(prompt_text),
               "focus": dict(sorted((focus or {}).items()))})


def decisions(problems, roots, plan, leadership, roi) -> dict:
    return {
        "problems": sorted(problems),
        "roles": {r.problem: r.role for r in roots.causes},
        "winner": [(a.action, a.phase) for a in sorted(plan.actions, key=lambda a: (a.phase, a.action))],
        "leadership": {d.intervention_id: [d.decision, d.to_phase] for d in leadership},
        "roi": [round(roi.cost_eur), round(roi.benefit_expected_eur, -3)],
    }


def check(fp: str, dec: dict) -> Stability:
    sig = _h(dec)
    try:
        ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        ledger = {}
    prev = ledger.get(fp)
    diffs = []
    if prev:
        old = prev["decisions"]
        for k in dec:
            if json.dumps(dec[k], sort_keys=True, default=str) != json.dumps(old.get(k), sort_keys=True, default=str):
                diffs.append(f"{k}: was {json.dumps(old.get(k), default=str)[:200]} now {json.dumps(dec[k], default=str)[:200]}")
    runs = prev["runs"] if prev else 0
    if not prev or not diffs:   # keep the first answer as the reference; record repeats
        ledger[fp] = {"signature": sig, "decisions": dec, "runs": runs + 1}
    else:
        ledger[fp]["runs"] = runs + 1
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(ledger, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    return Stability(fingerprint=fp, signature=sig, previous_runs=runs,
                     same_as_previous=None if not prev else not diffs, differences=diffs)
