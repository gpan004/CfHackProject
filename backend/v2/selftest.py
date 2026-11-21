"""Engine v2 self-tests (no network). Run: python -m backend.v2.selftest

1. every fact in kg_facts.json is backed by a verbatim quote (and a fake quote is caught)
2. the reference graph is typed, sourced, and never mutated by a client layer
3. the 10 tools are deterministic: same input -> identical output
4. dataset expectations (guardrails, root causes, plans) for the 3 scenarios
5. full pipeline with a MISBEHAVING fake LLM: invented quotes/sites/numbers/actions must all be caught
"""
import asyncio
import json
import re

from ..ingest import scenarios
from ..schemas import RunRequest
from . import agents as AG, brief as BR, kg, llm as L
from .schemas import (Diagnosis, ProblemView, Quote, SkepticReport, Challenge, StrategyDrafts, StrategyDraft, PlanChoice,
                      OriginalIdea, DroppedAction, CriticReview, JurorBallot, RubricScore, ReportDraft, ReportSection)
from .tools import (load_scenario, check_metrics, find_root_causes, allowed_actions, canonical_plan, schedule_phases,
                    rank_cases, calculate_roi, verify_quote)

A, B, C = (s["scenario_code"] for s in scenarios())


def deterministic_chain(code):
    c, G = load_scenario(code)
    sig = check_metrics(G, c)
    rc = find_root_causes(G, c, [s for s in sig if s.status == "confirmed"])
    gates = allowed_actions(G, c)
    targets = [r.problem for r in rc.causes if r.role != "symptom"]
    items = canonical_plan(G, c, rc, gates, targets)
    sched, _ = schedule_phases(G, c, items)
    cases = rank_cases(G, c, rc, sig)
    roi, _ = calculate_roi([a.action for a in sched], [x.case for x in cases[:3]], c)
    return {"sig": [s.model_dump() for s in sig], "rc": rc.model_dump(), "gates": {k: v.model_dump() for k, v in gates.items()},
            "plan": [a.model_dump() for a in sched], "cases": [x.model_dump() for x in cases], "roi": roi.model_dump()}


def test_facts_and_graph():
    assert kg.validate_facts() == [], kg.validate_facts()
    assert not kg.quote_in_doc("R1", "organizations with a severe say-do gap triple their revenue")   # invented quote
    G = kg.reference_graph()
    st = kg.graph_stats(G)
    for k in ("problem", "action", "worker", "case", "snippet", "field_note", "metric", "condition", "pillar"):
        assert st["nodes"].get(k), k
    for r in ("causes", "fixes", "changes", "needs_first", "fits", "blocked_by", "had_problem", "used", "workers",
              "threshold_for", "effect_on", "indicated_by", "closes"):
        assert st["edges"].get(r), r
    for u, v, d in G.edges(data=True):
        assert d["origin"] and isinstance(d["evidence"], list), (u, v, d)
        if d["rel"] in ("causes", "effect_on", "threshold_for", "closes"):
            assert all(kg.quote_in_doc(e["ref"], e["quote"]) for e in d["evidence"]), (u, v)
    n0 = G.number_of_nodes()
    c, G2 = load_scenario(A)
    assert G.number_of_nodes() == n0 and "value" not in G.nodes["external_claims_gap_stars_5"], "reference graph mutated"
    assert G2.nodes["external_claims_gap_stars_5"]["value"] == 1.3
    print("facts & graph OK", st["nodes"])


def test_determinism_and_expectations():
    for code in (A, B, C):
        assert json.dumps(deterministic_chain(code), sort_keys=True) == json.dumps(deterministic_chain(code), sort_keys=True), code
    ca, Ga = load_scenario(A)
    g = allowed_actions(Ga, ca)
    assert g["compensation_review"].rule == "do_not_touch" and g["retail_shift_rotation"].rule == "sector_fit"
    assert g["mobile_fast_apply"].rule == "sector_fit" and g["ambassador_selection"].earliest_phase == 3
    sig = {s.problem: s for s in check_metrics(Ga, ca)}
    assert sig["compensation"].status == "healthy" and sig["say_do_gap"].status == "confirmed"
    assert any("1.1" in t for m in sig["say_do_gap"].measured for t in m.thresholds), "R1 threshold not applied"
    rc = {r.problem: r for r in find_root_causes(Ga, ca, [s for s in sig.values() if s.status == "confirmed"]).causes}
    assert rc["weak_middle_management"].role == "root" and rc["early_attrition"].role == "symptom"
    plan_a = {a["action"]: a for a in deterministic_chain(A)["plan"]}
    assert "manager_coaching" in plan_a and plan_a["internal_listening_360"]["phase"] < plan_a["manager_coaching"]["phase"]
    assert plan_a.get("technical_storytelling", {"phase": 3})["phase"] == 3
    cb, Gb = load_scenario(B)
    rb = find_root_causes(Gb, cb, [s for s in check_metrics(Gb, cb) if s.status == "confirmed"])
    assert any(l.source == "slow_hiring" and l.target == "agency_dependency" for l in rb.links)
    assert "mobile_fast_apply" in {a["action"] for a in deterministic_chain(B)["plan"]}
    cc, Gc = load_scenario(C)
    gc = allowed_actions(Gc, cc)
    assert gc["evp_realignment"].rule == "do_not_touch" and gc["manager_coaching"].rule == "do_not_touch"
    assert not verify_quote("signals.reputation_and_reviews", "invented sentence nobody wrote", ca).ok
    assert AG.strip_numbers("Fine sentence [C05]. Revenue grows 40%.")[0] == "Fine sentence [C05]."
    assert AG.verify_scope("Mars Office", ca) == ("company-wide", False)
    assert AG.verify_scope("Milan and Berlin product squads", ca)[1]
    toks = {"cost": "€1"}
    assert BR.validate_sentence("Start with 360-Degree Internal Listening [FN5].", Ga, ca, toks)[0]      # digits in a name are fine
    assert BR.validate_sentence("See [C<number>] for details.", Ga, ca, toks)[0] is None                 # placeholder copied
    assert BR.validate_sentence("It saves 40% [C05].", Ga, ca, toks)[0] is None                         # model-written number
    assert BR.NUM_RE.sub("<n>", "C05 shows 22% and €1,350,000 [FN4]") == "C05 shows <n> and <n> [FN4]"
    wrong = "Compensation already beats peers ({{compare:sub_ratings_5.career_growth}})."      # right number, wrong metric
    right = "Compensation already beats peers ({{compare:sub_ratings_5.compensation}})."
    assert BR.validate_sentence(wrong, Ga, ca, toks)[0] is None
    assert "4.18 stars vs peers 3.68 stars" in BR.validate_sentence(right, Ga, ca, toks)[0]
    print("determinism & expectations OK")


# ---------- a deliberately misbehaving fake LLM ----------
def _ids(pattern, text):
    return list(dict.fromkeys(re.findall(pattern, text)))


async def fake_call(role, tier, system, user, schema, fresh=False):
    info = {"model": "fake", "cached": False, "attempts": 1}
    if schema is Diagnosis:
        ids = _ids(r"^\* ([a-z_]+):", re.sub(r"(?m)^\s+", "", user)) or _ids(r"\* ([a-z_]+):", user)
        return Diagnosis(pillar=role.split(":")[1], problems=[ProblemView(
            problem=i, agree=True, scope="Mars Office" if k == 0 else "company-wide",
            explanation="This costs 3 million euros. Teams feel it every day.",
            quotes=[Quote(ref="narrative", quote="an invented sentence that is not in the data")]) for k, i in enumerate(ids)]), info
    if schema is SkepticReport:
        ids = _ids(r"\* ([a-z_]+):", user)
        return SkepticReport(challenges=[Challenge(problem=i, verdict="refuted" if k == 0 else "holds",
                                                   reason="no proof", counter_quotes=[]) for k, i in enumerate(ids)]), info
    if schema is StrategyDrafts:
        pids = _ids(r"\* (P\d) variant=", user)
        plans = []
        for pid in pids:
            block = user.split(f"* {pid} variant=")[1].split("\n* ")[0].split("\n\n")[0]
            acts = _ids(r"- ([a-z_0-9]+) \(", block)
            plans.append(StrategyDraft(
                plan_id=pid, title=f"Plan {pid}", thesis="We will cut attrition by 30% in 6 months.",
                choices=[PlanChoice(action=a, scope="Atlantis hub", why="Because.") for a in acts[1:]]
                        + [PlanChoice(action="compensation_review", scope="company-wide", why="Pay more."),
                           PlanChoice(action="hire_a_wizard", scope="company-wide", why="Magic.")],
                original_ideas=[OriginalIdea(title="Moon office", description="Open an office on the moon.",
                                             fixes=["made_up_problem"], evidence=["C99"], phase=2),
                                OriginalIdea(title="Lead-to-manager bridge", description="Pair new team leads with a senior mentor.",
                                             fixes=["weak_middle_management"], evidence=["C05", "R4"], phase=2)],
                dropped=[]))
        return StrategyDrafts(plans=plans), info
    if schema is CriticReview:
        return CriticReview(issues=[]), info
    if schema is JurorBallot:
        pids = _ids(r"plan_id=(P\d)", user)
        return JurorBallot(persona="x", scores=[RubricScore(plan_id=p, feasibility=4, impact=4, evidence=4, risk=2,
                                                             cites=["nonexistent"] if k else [], concern="none",
                                                             verdict="reject" if k == 0 else "approve")
                                                 for k, p in enumerate(pids)]), info
    if schema is ReportDraft:
        return ReportDraft(headline="Fix the root causes first", sections=[
            ReportSection(heading=h, text="Costs are {{cost}} [C05]. It saves 2 million. See [Z99]. Plain words help.")
            for h in BR.HEADINGS]), info
    raise AssertionError(schema)


def test_pipeline_with_bad_llm():
    import tempfile
    from pathlib import Path
    from . import pipeline as PL, consistency as CO
    orig = (AG.call, BR.call, CO.LEDGER)
    AG.call = BR.call = fake_call
    CO.LEDGER = Path(tempfile.mkdtemp()) / "ledger.json"          # never touch the real stability ledger
    try:
        r = asyncio.run(PL.run_pipeline_v2(RunRequest(scenario_code=A), run_id="selftest_v2"))
        r2 = asyncio.run(PL.run_pipeline_v2(RunRequest(scenario_code=A), run_id="selftest_v2"))
    finally:
        AG.call, BR.call, CO.LEDGER = orig
    assert r2.stability.same_as_previous is True, r2.stability.differences
    notes = " ".join(n for t in r.trace for n in t.notes)
    assert "removed unverifiable quote" in notes and "scope not found" in notes and "removed sentence with a number" in notes
    assert "downgraded to 'weaker'" in notes
    kinds = {i.kind for rnd in r.critic_rounds for i in rnd.issues}
    assert {"rule_violation", "unjustified_drop", "original_unsupported", "unsupported_claim", "scope_problem"} <= kinds, kinds
    assert len(r.critic_rounds) >= 2, "critic should have sent the plans back"
    for p in r.plans:
        acts = {a.action for a in p.actions}
        assert "compensation_review" not in acts and "hire_a_wizard" not in acts
        assert [a.label for a in p.actions if a.original] == ["Lead-to-manager bridge"], "only the supported original idea may survive"
        assert all(a.scope == "company-wide" for a in p.actions), "invented scope survived"
        assert not re.search(r"\d", p.thesis), "model-written number survived"
        assert {"manager_coaching", "career_framework"} <= acts or p.variant == "core", (p.variant, acts)
    assert r.jury_audit and any("cites nothing" in f for f in r.jury_audit.flags)
    assert any("contradicts its own scores" in f for f in r.jury_audit.flags)
    assert r.brief.dropped_sentences and all("[Z99]" not in s.text and "million" not in s.text for s in r.brief.sections)
    assert any("€" in s.text for s in r.brief.sections), "{{cost}} token not rendered"
    print("pipeline with a misbehaving LLM OK:",
          f"{sum(len(x.issues) for x in r.critic_rounds)} critic issues, {len(r.jury_audit.flags)} jury flags, "
          f"{len(r.brief.dropped_sentences)} report sentences dropped; winner {r.winner}")


if __name__ == "__main__":
    test_facts_and_graph()
    test_determinism_and_expectations()
    test_pipeline_with_bad_llm()
    print("v2 selftest OK")
