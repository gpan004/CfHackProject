
import asyncio
import json
import re

from ..ingest import scenarios
from ..schemas import RunRequest
from . import agents as AG, brief as BR, kg, llm as L, factcheck as FC
from .schemas import (Diagnosis, ProblemView, Quote, SkepticReport, Challenge, StrategyDrafts, StrategyDraft, PlanChoice,
                      OriginalIdea, DroppedAction, CriticReview, JurorBallot, RubricScore, ReportDraft, ReportSection,
                      FactCheckDraft, ClaimVerdict)
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
            ReportSection(heading=h, text="Costs are {{cost}} [C05]. It saves 2 million. See [Z99]. Plain words help. "
                                          "Milan managers caused a strike last year. "
                                          "Manager coaching fixes the promise vs reality gap [C06].")
            for h in BR.HEADINGS]), info
    if schema is FactCheckDraft:                     # an honest checker: flags the planted hallucination only
        sents = re.findall(r"(?m)^(\d+)\. \[[^\]]*\] (.*)$", user)
        return FactCheckDraft(verdicts=[ClaimVerdict(id=int(i), verdict="unsupported" if "strike" in s else "supported",
                                                     reason="no strike in the facts" if "strike" in s else "ok")
                                        for i, s in sents]), {"model": "fake-checker", "cached": False, "attempts": 1}
    raise AssertionError(schema)


def test_pipeline_with_bad_llm():
    import tempfile
    from pathlib import Path
    from . import pipeline as PL, consistency as CO
    orig = (AG.call, BR.call, FC.call, CO.LEDGER)
    AG.call = BR.call = FC.call = fake_call
    CO.LEDGER = Path(tempfile.mkdtemp()) / "ledger.json"          # never touch the real stability ledger
    try:
        r = asyncio.run(PL.run_pipeline_v2(RunRequest(scenario_code=A), run_id="selftest_v2"))
        r2 = asyncio.run(PL.run_pipeline_v2(RunRequest(scenario_code=A), run_id="selftest_v2"))
    finally:
        AG.call, BR.call, FC.call, CO.LEDGER = orig
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
    # fact-checker: layer 2 removed the planted hallucination, layer 1 removed the irrelevant citation
    fc = r.brief.fact_check
    assert fc.status == "ran" and fc.checked > 0 and any("strike" in x.text for x in fc.removed)
    assert all("strike" not in s.text for s in r.brief.sections), "hallucinated sentence survived"
    assert any("[C06]" in c for c in fc.citations_removed) and all("[C06]" not in s.text for s in r.brief.sections)
    assert any("Manager coaching fixes the promise" in s.text for s in r.brief.sections), "a sentence lost more than its citation"
    assert r.fact_check.status == "ran" and r.fact_check.checked > 0, "plans were not fact-checked"
    print("pipeline with a misbehaving LLM OK:",
          f"{sum(len(x.issues) for x in r.critic_rounds)} critic issues, {len(r.jury_audit.flags)} jury flags, "
          f"{len(r.brief.dropped_sentences)} report sentences dropped; winner {r.winner}")


def test_steering():
    from . import steering as ST, consistency as CO
    from .schemas import WhatIfRequest, RequestCheckRequest
    all_less = ST.normalize_focus({p: "less" for p in ST.PILLARS})
    assert ST.is_neutral(all_less) and "not be effective" in all_less.warnings[0]
    assert ST.is_neutral(ST.normalize_focus({p: "more" for p in ST.PILLARS}))
    three = ST.normalize_focus({"branding": "less", "recruiting": "less", "advocacy": "less"})
    assert not ST.is_neutral(three) and "less effective" in three.warnings[0]
    assert ST.normalize_focus({"retention": "bogus"}).effective["retention"] == "normal"
    # what-if: deterministic, rules never change, warnings when the top root cause is deprioritised
    req = WhatIfRequest(scenario_code=B, focus={"recruiting": "less"})
    w1, w2 = ST.what_if(req), ST.what_if(req)
    assert w1.model_dump_json() == w2.model_dump_json()
    neutral = ST.what_if(WhatIfRequest(scenario_code=B))
    assert w1.unchanged_rules == neutral.unchanged_rules, "priorities changed a guardrail"
    assert any("highest-priority root cause" in x for x in w1.focus.warnings)
    assert w1.diff.removed and w1.roi_after.benefit_expected_eur < w1.roi_before.benefit_expected_eur
    wa = ST.what_if(WhatIfRequest(scenario_code=A, focus={"retention": "more"}))
    assert "early_attrition" in wa.focus.added_symptoms
    assert {r.problem for r in wa.priorities} == {r.problem for r in ST.what_if(WhatIfRequest(scenario_code=A)).priorities}, \
        "priorities must not add or remove problems"
    c, _ = load_scenario(A)
    assert CO.fingerprint(c, {"retention": "more"}) != CO.fingerprint(c, {"retention": "normal"})
    # request checker
    chk = lambda code, t: ST.check_request(RequestCheckRequest(scenario_code=code, text=t))
    r = chk(A, "Let's launch ambassadors now")
    assert [m.action for m in r.matches] == ["ambassador_selection"] and r.matches[0].verdict == "later" \
        and r.matches[0].phase == 3 and {"FN4", "R5"} <= {e.ref for e in r.matches[0].evidence}
    r = chk(A, "We want a salary review for engineers")
    assert r.matches[0].verdict == "no" and "strength to protect" in r.matches[0].headline
    r = chk(B, "Marketing wants a LinkedIn blog series to attract drivers")
    assert r.matches[0].action == "technical_storytelling" and r.matches[0].verdict == "no"
    assert "knowledge worker" in r.matches[0].reason and "_" not in r.matches[0].reason
    assert [m.action for m in chk(A, "track ambassador posts automatically").matches] == ["ambassador_tracking"]
    assert not chk(A, "Give everyone a pizza party").understood
    # broader matching (bug report: "run linkedin campaign" was not understood)
    li = chk(A, "run linkedin campaign")
    assert li.understood and {m.action for m in li.matches} == {"ambassador_selection", "technical_storytelling"}
    co = chk(A, "coaching for our new managers")
    assert co.understood and co.interpreted and co.matches[0].action == "manager_coaching" and co.matches[0].matched_on
    ag = chk(B, "hire a recruitment agency")
    assert not ag.understood and "problem to reduce" in ag.note and ag.suggestions, "a problem must point to its fixes"
    assert len(ST.catalog_for(WhatIfRequest(scenario_code=B))) == 16
    assert "_" not in chk(B, "deploy the fast-apply widget tomorrow").matches[0].reason, "raw ids leaked into the reason"
    print("steering (priorities, what-if, request checker) OK")


def test_readers_with_fake_llm():
    import tempfile
    from pathlib import Path
    from . import pipeline as PL, consistency as CO
    from .schemas import RunRequestV2
    orig = (AG.call, BR.call, FC.call, CO.LEDGER)
    AG.call = BR.call = FC.call = fake_call
    CO.LEDGER = Path(tempfile.mkdtemp()) / "ledger.json"
    try:
        r = asyncio.run(PL.run_pipeline_v2(RunRequestV2(scenario_code=A, focus={"retention": "more"}, audience="cfo"),
                                           run_id="selftest_v2_cfo"))
        hr, _ = asyncio.run(BR.rewrite_for(r, "hr"))
    finally:
        AG.call, BR.call, FC.call, CO.LEDGER = orig
    prof = lambda a: kg.facts()["audiences"][a]
    assert r.plans[0].variant == "focus" and r.focus.effective["retention"] == "more"
    assert [s.heading for s in r.brief.sections] == prof("cfo")["order"] and r.brief.one_minute[0]["title"] == "The payoff"
    assert [s.heading for s in hr.sections] == prof("hr")["order"] and hr.one_minute[0]["title"] == "The first move"
    core = {f"€{r.roi.cost_eur:,.0f}"}          # the fake writer only uses the {{cost}} token
    for b in (r.brief, hr):
        assert core <= set(re.findall(r"€[\d,]+", " ".join(s.text for s in b.sections))), "a reader change altered a core figure"
    assert "more weight to Retention" in " ".join(s.text for s in r.brief.sections)
    print("readers (CFO / HR / Board) OK: same numbers, different order and emphasis")


def test_all_models_down():
    """Quota exhausted / no network: the run must still finish with a complete, rule-based answer."""
    import tempfile
    from pathlib import Path
    from . import pipeline as PL, consistency as CO
    from .schemas import RunRequestV2

    async def down(*a, **k):
        raise L.LLMError("429 rate limit (simulated)")
    orig = (AG.call, BR.call, FC.call, CO.LEDGER)
    AG.call = BR.call = FC.call = down
    CO.LEDGER = Path(tempfile.mkdtemp()) / "ledger.json"
    try:
        r = asyncio.run(PL.run_pipeline_v2(RunRequestV2(scenario_code=B, focus={"recruiting": "more"}, audience="hr"),
                                           run_id="selftest_v2_offline"))
    finally:
        AG.call, BR.call, FC.call, CO.LEDGER = orig
    notes = " ".join(n for t in r.trace for n in t.notes)
    assert "diagnosticians unavailable" in notes and "strategist unavailable" in notes
    assert {"Diagnosticians", "Strategist", "Report writer"} <= set(r.degraded), r.degraded
    win = next(p for p in r.plans if p.plan_id == r.winner)
    assert "mobile_fast_apply" in {a.action for a in win.actions} and r.brief.writer == "template"
    assert [s.heading for s in r.brief.sections] == kg.facts()["audiences"]["hr"]["order"]
    assert not any("sub_ratings_5" in p for p in r.protected), "raw metric keys in the protected list"
    brief_text = " ".join(s.text for s in r.brief.sections) + " ".join(r.leadership_views.values())
    assert not re.search(r"\b[a-z]+(?:_[a-z0-9]+)+\b", brief_text), re.findall(r"\b[a-z]+(?:_[a-z0-9]+)+\b", brief_text)
    print("all models down OK: complete rule-based answer, winner", r.winner, f"({win.variant})")


def test_reader_wording_and_switch():
    """Bug reports: (1) changing the reader only reordered the text; (2) switching was slow every time."""
    import tempfile
    from pathlib import Path
    from fastapi.testclient import TestClient
    from . import pipeline as PL, consistency as CO
    from .schemas import RunRequestV2, RunStateV2
    from .. import main as M

    calls = {"n": 0}

    async def down(*a, **k):
        calls["n"] += 1
        raise L.LLMError("429 daily quota (simulated)")
    orig = (AG.call, BR.call, FC.call, CO.LEDGER)
    AG.call = BR.call = FC.call = down
    CO.LEDGER = Path(tempfile.mkdtemp()) / "ledger.json"
    try:
        r = asyncio.run(PL.run_pipeline_v2(RunRequestV2(scenario_code=A, audience="board"), run_id="selftest_v2_switch"))
        texts = {}
        for a in ("board", "cfo", "hr"):
            b, _ = asyncio.run(BR.rewrite_for(r, a))
            texts[a] = {s.heading: s.text for s in b.sections}
        # (1) real rewording, not only order: every reader differs in the problem and cause sections
        for h in ("What is going on", "Why it is happening", "What to do, in what order"):
            assert len({texts[a][h] for a in texts}) == 3, f"'{h}' is worded the same for different readers"
        # ...with the same facts: every euro figure of the board brief appears in the CFO brief
        eur = lambda t: set(re.findall(r"€[\d,]+", " ".join(t.values())))
        assert eur(texts["board"]) <= eur(texts["cfo"]), eur(texts["board"]) - eur(texts["cfo"])
        # (2) switching back to a reader already written is instant (no model call); retry only on request
        M.RUNS_V2["t"] = RunStateV2(run_id="t", status="done", result=r)
        cl = TestClient(M.app)
        first = cl.post("/api/v2/runs/t/brief?audience=cfo").json()
        n_after_first = calls["n"]
        again = cl.post("/api/v2/runs/t/brief?audience=cfo").json()
        assert again["stored"] and calls["n"] == n_after_first, "a known reader called the model again"
        cl.post("/api/v2/runs/t/brief?audience=cfo&retry=true")
        assert calls["n"] > n_after_first, "retry did not try the AI writer"
        assert first["brief"]["writer"] == "template"
    finally:
        AG.call, BR.call, FC.call, CO.LEDGER = orig
        M.RUNS_V2.pop("t", None)
    print("reader wording differs per reader (same figures); known readers switch instantly OK")


def test_more_has_effect():
    """Bug report: Less -> More changed almost nothing."""
    from . import steering as ST
    from .schemas import WhatIfRequest
    w = ST.what_if(WhatIfRequest(scenario_code=A, focus={"recruiting": "more"}))
    assert w.diff.added, "More on a pillar with fixable problems must add actions"
    e = ST.what_if(WhatIfRequest(scenario_code=B, focus={"retention": "more"}))
    assert any("no confirmed problem" in x for x in e.focus.warnings), "no-effect case must be explained"
    f = ST.what_if(WhatIfRequest(scenario_code=B, focus={"recruiting": "more"}))
    assert any("already in the plan" in s for s in f.summary), "saturated pillar must be explained"
    print("More adds actions, or explains why it cannot OK")


if __name__ == "__main__":
    test_facts_and_graph()
    test_determinism_and_expectations()
    test_pipeline_with_bad_llm()
    test_steering()
    test_readers_with_fake_llm()
    test_all_models_down()
    test_reader_wording_and_switch()
    test_more_has_effect()
    print("v2 selftest OK")
