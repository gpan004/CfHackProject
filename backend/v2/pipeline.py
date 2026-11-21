"""Engine v2 orchestrator. CLI: python -m backend.v2.pipeline --scenario CODE [--fresh]

intake -> measure -> diagnose (4 agents) -> challenge (skeptic) -> root causes -> precedents -> gates -> draft plans
-> strategist <-> plan critic (max 2 revisions) -> final plans -> jury -> jury critic -> ROI -> report writer -> stability
"""
import argparse
import asyncio
import time
import uuid

from ..config import RUNS_DIR
from ..guardrails import place_requests
from ..knowledge import CATALOG
from ..schemas import PlanAction, RunRequest
from . import agents as AG
from . import brief as BR
from . import steering as ST
from . import factcheck as FC
from .consistency import fingerprint, decisions, check
from .kg import documents, label, doc_links
from .llm import FRESH
from .schemas import ResultV2, TraceV2, PlanV2, CriticRound, DroppedAction, RunRequestV2, StrategyDrafts
from .tools import (load_scenario, check_metrics, find_root_causes, rank_cases, allowed_actions, canonical_plan,
                    schedule_phases, calculate_roi, action_cost, explain_action, check_relevance)

STAGES_V2 = ["intake", "measure", "diagnose", "challenge", "root_causes", "precedents", "gates", "strategy",
             "critic", "plans", "fact_check", "jury", "jury_critic", "stability", "report"]
MAX_REVISIONS = 1      # live runs showed a second revision tends to add issues; Python auto-fixes what remains


def _variants(G, client, roots, gates, fi=None):
    w = {r.problem: r.weight for r in roots.causes}
    full_t = [r.problem for r in roots.causes if r.role in ("root", "standalone", "intermediate")]
    core_t = sorted([r.problem for r in roots.causes if r.role in ("root", "standalone")], key=lambda p: (-w[p], p))[:3]
    specs = [("full", "Fix every root cause and the problems in between.", full_t, False),
             ("core", "Focus on the three highest-priority root causes; leave the rest for later.", core_t, False),
             ("lean", "Cover every root cause at the lowest cost.", full_t, True),
             ("quick", "Only actions that can start in the first two phases.", full_t, False)]
    if fi is not None and not ST.is_neutral(fi):      # the client's priorities get their own variant, listed first
        focus_t, _, _ = ST.focused_targets(G, roots, fi)
        specs = [("focus", ST.focus_sentence(fi).replace("At the client's request, the plan gives", "Follow the client's "
                  "priorities: give").rstrip(".") + ".", focus_t, False)] + [s for s in specs if s[0] != "core"]
    out, seen = [], set()
    for name, emph, targets, budget in specs:
        g = gates if name != "quick" else {a: x for a, x in gates.items() if x.earliest_phase <= 2 and CATALOG[a]["type"] != "amplification"}
        items = (ST.focus_items(G, client, roots, g, fi, targets) if name == "focus"
                 else canonical_plan(G, client, roots, g, targets, budget_mode=budget))
        key = tuple(sorted(i["action"] for i in items))
        if not items or key in seen:
            continue
        seen.add(key)
        out.append({"plan_id": f"P{len(out) + 1}", "variant": name, "emphasis": emph, "targets": targets, "items": items})
        if len(out) == 3:
            break
    return out


AGENT_NAMES = {"diagnosticians": "Diagnosticians", "skeptic": "Skeptic", "strategist": "Strategist",
               "LLM critic": "Plan critic (AI part)", "juror": "Jury", "report writer": "Report writer",
               "fact-checker": "Fact-checker"}


def degraded_agents(trace) -> list[str]:
    """Which agents could not run, read from the trace notes (so the page can say it plainly)."""
    out = []
    for t in trace:
        for n in t.notes:
            low = n.lower()
            for key, name in AGENT_NAMES.items():
                if key.lower() in low and ("unavailable" in low or "failed" in low) and name not in out:
                    out.append(name)
    return out


def _apply_draft(G, client, draft, v, gates, targets, issues, roots):
    """Turns a strategist draft into schedulable items. Python auto-fixes what the critic still finds wrong."""
    blocking_orig = {i.target for i in issues if i.plan_id == v["plan_id"] and i.kind == "original_unsupported"}
    items, by_action = [], {i["action"]: i for i in v["items"]}
    dropped_ok = []
    for ch in (draft.choices if draft else []):
        if ch.action in CATALOG and gates[ch.action].allowed and ch.action not in {i["action"] for i in items}:
            base = by_action.get(ch.action) or {"fixes": sorted(set(CATALOG[ch.action]["fixes_concepts"]) & set(targets)),
                                                "evidence": []}
            scope, _ = AG.verify_scope(ch.scope, client)
            why, _ = AG.strip_numbers(ch.why)
            items.append({"action": ch.action, "fixes": base["fixes"], "evidence": base["evidence"], "scope": scope,
                          "source": "plan", "rationale": why})
    dropped = {d.action: d for d in (draft.dropped if draft else [])}
    chosen = {i["action"] for i in items}
    for it in v["items"]:
        if it["action"] in chosen:
            continue
        others = {p for i in items for p in CATALOG[i["action"]]["fixes_concepts"]}
        sole_cover = any(p not in others for p in it["fixes"])
        j = AG.strip_numbers(dropped[it["action"]].justification)[0] if it["action"] in dropped else ""
        if j and not sole_cover:
            dropped_ok.append(DroppedAction(action=it["action"], justification=j))
        else:
            items.append(dict(it, rationale=""))      # re-added: unjustified drop or the only cover of a target
    for o in (draft.original_ideas if draft else []):
        if o.title in blocking_orig:
            continue
        desc, _ = AG.strip_numbers(o.description)
        ev = [e for e in o.evidence if e in documents() and (G.nodes[e]["kind"] not in ("case", "snippet")
                                                             or check_relevance(G, e, client).relevant)
              and doc_links().get(e, frozenset()) & set(o.fixes)]
        items.append({"action": "original", "title": o.title, "description": desc, "fixes": [p for p in o.fixes if p in targets],
                      "evidence": ev, "phase": o.phase, "scope": "company-wide", "source": "original", "rationale": desc})
    covered = {p for i in items for p in (CATALOG[i["action"]]["fixes_concepts"] if i["action"] in CATALOG else i["fixes"])}
    missing = [p for p in v["targets"] if p not in covered]
    if missing:
        for it in canonical_plan(G, client, roots, gates, missing):
            if it["action"] not in {i["action"] for i in items}:
                items.append(dict(it, rationale=""))
    return items, dropped_ok


def _score_plans(plans, targets_all, roots, cases, client):
    w = {r.problem: r.weight + 0.1 for r in roots.causes}
    tot = sum(w.get(p, 0.1) for p in targets_all) or 1
    case_ids = [c.case for c in cases if c.worker_fit and c.score > 0][:3]
    rois = {}
    for p in plans:
        covered = {f for a in p.actions for f in a.fixes}
        p.coverage = round(sum(w.get(t, 0.1) for t in targets_all if t in covered) / tot, 4)
        own = [a for a in p.actions if a.source != "auto_added"]
        p.evidence_strength = round(sum(bool(a.precedents or a.evidence) for a in own) / (len(own) or 1), 4)
        p.cost_eur = sum(action_cost(a.action if not a.original else "original") for a in p.actions)
        roi, _ = calculate_roi([a.action if not a.original else "original" for a in p.actions], case_ids, client)
        rois[p.plan_id] = roi.roi_expected or 0.0
    best = max([r for r in rois.values() if r > 0], default=0)
    for p in plans:
        eff = min(1.0, max(0.0, rois[p.plan_id] / best)) if best > 0 else 0.0
        p.det_score = round(0.5 * p.coverage + 0.3 * p.evidence_strength + 0.2 * eff, 4)


async def run_pipeline_v2(req: RunRequest, on_stage=None, run_id: str | None = None, fresh: bool = False) -> ResultV2:
    run_id = run_id or uuid.uuid4().hex[:10]
    on_stage = on_stage or (lambda name, done: None)
    FRESH.set(fresh)
    fi = ST.normalize_focus(getattr(req, "focus", None))
    audience = getattr(req, "audience", "board") or "board"
    trace: list[TraceV2] = []
    S = {}

    async def stage(name, kind, fn):
        on_stage(name, False)
        t, calls, notes = time.time(), [], []
        out = await fn(calls, notes) if asyncio.iscoroutinefunction(fn) else fn(calls, notes)
        trace.append(TraceV2(stage=name, seconds=round(time.time() - t, 2), kind=kind,
                             models=sorted({c["model"] for c in calls}), cached=bool(calls) and all(c["cached"] for c in calls),
                             notes=notes))
        on_stage(name, True)
        return out

    def s_intake(calls, notes):
        c, G = load_scenario(req.scenario_code, req.scenario, req.snapshot, req.overrides)
        notes += [f"workforce: {', '.join(c.archetypes) or 'unknown'}", f"{len(c.metrics)} metrics, {len(c.segments)} sites",
                  f"hygiene: {len(c.noise)} noise sentence(s) removed"] + [f"noise: {n.sentence[:80]} ({n.reason})" for n in c.noise]
        return c, G
    client, G = await stage("intake", "tool", s_intake)

    def s_measure(calls, notes):
        sig = check_metrics(G, client)
        notes.append(", ".join(f"{s.problem}={s.status}" for s in sig))
        return sig
    signals = await stage("measure", "tool", s_measure)

    async def s_diag(calls, notes):
        try:
            return await AG.diagnose(client, signals, calls)
        except Exception as e:  # noqa: BLE001 - degrade: metrics-confirmed problems only
            notes.append(f"diagnosticians unavailable ({str(e)[:120]}): only problems confirmed by metrics are used")
            return [], {s.problem: {"contested": False, "scope": "company-wide", "explanation": s.plain}
                        for s in signals if s.status == "confirmed"}, []
    diagnoses, accepted, n1 = await stage("diagnose", "agent", s_diag)
    trace[-1].notes += n1

    async def s_chal(calls, notes):
        try:
            ch, acc, n = await AG.challenge(client, signals, accepted, calls)
        except Exception as e:  # noqa: BLE001 - degrade: no challenge
            notes.append(f"skeptic unavailable ({str(e)[:120]}): diagnosis not challenged")
            return [], accepted
        notes += n
        return ch, acc
    challenges, accepted = await stage("challenge", "agent", s_chal)
    if not accepted:
        raise RuntimeError("no problem survived diagnosis and challenge")
    by_sig = {s.problem: s for s in signals}

    def s_roots(calls, notes):
        r = find_root_causes(G, client, [by_sig[p] for p in accepted])
        notes += [f"{x.problem}: {x.role} (priority {x.weight:.2f})" for x in r.causes]
        notes.append(f"{sum(l.origin == 'reference' for l in r.links)} dataset links, "
                     f"{sum(l.origin == 'client_text' for l in r.links)} client-text links, 0 LLM-made links")
        return r
    roots = await stage("root_causes", "tool", s_roots)
    if not ST.is_neutral(fi):
        neutral_roots = roots
        roots = ST.apply_focus(G, roots, fi)
        _, fi.deferred, fi.added_symptoms = ST.focused_targets(G, roots, fi)
        fi.warnings += ST.focus_warnings(G, neutral_roots, fi, fi.deferred)
        trace[-1].notes.append("client priorities: " + ", ".join(f"{p}={fi.effective[p]}" for p in ST.PILLARS)
                               + " -> priorities re-weighted (facts, evidence and rules unchanged)")
    trace[-1].notes += fi.warnings

    def s_prec(calls, notes):
        cs = rank_cases(G, client, roots, signals)
        notes += [f"{c.case}: {c.score:.2f} ({c.reason})" for c in cs[:4]]
        return cs
    cases = await stage("precedents", "tool", s_prec)

    def s_gates(calls, notes):
        g = allowed_actions(G, client)
        notes += [f"{a}: {x.rule} - {x.reason}" for a, x in g.items() if x.rule != "ok"]
        return g
    gates = await stage("gates", "tool", s_gates)
    variants = _variants(G, client, roots, gates, fi)
    targets_all = sorted({t for v in variants for t in v["targets"]})
    prelim = [PlanAction(action=label(G, i["action"]), intervention_id=i["action"], phase=1, target_scope="",
                         addresses=[], evidence=[]) for i in variants[0]["items"]]
    leadership = place_requests(client.leadership_requests, prelim, client)
    message = AG.strategy_message(client, G, roots, variants, gates, leadership, cases)
    more_p = [ST.pillar_label(p) for p in ST.PILLARS if fi.effective[p] == "more"]
    priorities_txt = "" if ST.is_neutral(fi) else (
        "\n\nCLIENT PRIORITIES (respect them; they never override the rules): "
        + ", ".join(f"{ST.pillar_label(p)} = {ST.WORD[fi.effective[p]]}" for p in ST.PILLARS)
        + (f"\nFor the plan with variant=focus, propose at least one original idea for each pillar set to More "
           f"({', '.join(more_p)}), aimed at its problems and backed by a document id." if more_p else ""))
    message += priorities_txt

    async def s_strategy(calls, notes):
        try:
            d = await AG.strategize(message, calls)
        except Exception as e:  # noqa: BLE001 - degrade: the graph's draft plans are used as they are
            notes.append(f"strategist unavailable ({str(e)[:120]}): the deterministic draft plans are used unrefined")
            return None
        notes.append(f"{len(d.plans)} plans, {sum(len(p.original_ideas) for p in d.plans)} original idea(s)")
        return d
    drafts = await stage("strategy", "agent", s_strategy)
    strategist_ok = drafts is not None
    if drafts is None:
        drafts = StrategyDrafts(plans=[])

    async def s_critic(calls, notes):
        nonlocal drafts
        if not strategist_ok:
            notes.append("no strategist output to review: plans come straight from the knowledge graph and the rules")
            return [CriticRound(round=1, issues=[], verdict="pass")]
        rounds = []
        for rnd in range(1, MAX_REVISIONS + 2):
            issues = AG.rule_check(G, client, drafts, variants, gates, set(accepted), leadership)
            try:
                issues += await AG.llm_critic(message, drafts, issues, calls)
            except Exception as e:  # noqa: BLE001 - rules still apply
                notes.append(f"round {rnd}: LLM critic unavailable ({str(e)[:100]}); rule checks only")
            blocking = [i for i in issues if i.severity == "blocking"]
            rounds.append(CriticRound(round=rnd, issues=issues, verdict="revise" if blocking else "pass"))
            notes.append(f"round {rnd}: {len(blocking)} blocking, {len(issues) - len(blocking)} minor")
            if not blocking or rnd > MAX_REVISIONS:
                break
            try:
                drafts = await AG.strategize(message, calls, issues=issues, previous=drafts)
            except Exception as e:  # noqa: BLE001
                notes.append(f"revision failed ({str(e)[:100]}); Python auto-fixes the remaining issues")
                break
        if rounds[-1].verdict == "revise":
            notes.append("remaining blocking issues auto-fixed by Python (invalid actions removed, unjustified drops "
                         "re-added, unsupported original ideas dropped, coverage completed from the graph)")
        return rounds
    critic_rounds = await stage("critic", "critic", s_critic)
    final_issues = critic_rounds[-1].issues

    def s_plans(calls, notes):
        out = []
        dmap = {d.plan_id: d for d in drafts.plans}
        problems_role = {r.problem: r.role.replace("_", " ") for r in roots.causes}
        for v in variants:
            d = dmap.get(v["plan_id"])
            items, dropped = _apply_draft(G, client, d, v, gates, v["targets"], final_issues, roots)
            sched, decisions_ = schedule_phases(G, client, items)
            rat = {i.get("title") or i["action"]: i.get("rationale", "") for i in items}
            for a in sched:
                key = a.label if a.original else a.action
                a.rationale = rat.get(key, "") or rat.get(a.action, "")
                a.paths = explain_action(G, client, a.action, problems_role) if not a.original else \
                    [f"Original idea → addresses {', '.join(label(G, p) for p in a.fixes) or '-'}; supported by {', '.join(a.evidence) or '-'}"]
            title = (d.title if d else v["emphasis"]) or v["variant"]
            thesis, _ = AG.strip_numbers(d.thesis if d else v["emphasis"])
            out.append(PlanV2(plan_id=v["plan_id"], title=title, thesis=thesis or v["emphasis"], variant=v["variant"],
                              actions=sched, decisions=decisions_, dropped=dropped))
        uniq, seen = [], {}
        for p in out:                       # refinement can make two variants identical: keep one, let the jury compare real choices
            key = tuple(sorted((a.action, a.phase) for a in p.actions))
            if key in seen:
                notes.append(f"{p.plan_id} ({p.variant}) ended up identical to {seen[key]} -> merged")
                continue
            seen[key] = p.plan_id
            uniq.append(p)
        out = uniq
        _score_plans(out, targets_all, roots, cases, client)
        notes += [f"{p.plan_id} ({p.variant}): {len(p.actions)} actions, coverage {p.coverage:.2f}, "
                  f"evidence {p.evidence_strength:.2f}, cost €{p.cost_eur:,.0f}, deterministic score {p.det_score:.3f}" for p in out]
        return out
    plans = await stage("plans", "tool", s_plans)
    vmap = {v["plan_id"]: v for v in variants}
    rejected_views: set[tuple[str, str]] = set()

    async def s_fact(calls, notes):
        """Fact-checker on everything the strategist and skeptic wrote that the client will read."""
        items, refs = [], []
        for p in plans:
            if p.thesis != vmap[p.plan_id]["emphasis"]:          # Python's own variant description needs no check
                items.append((f"{p.plan_id} thesis", p.thesis)); refs.append(("thesis", p, None))
            for a in p.actions:
                if a.rationale and not a.rationale.startswith("Added because"):
                    items.append((f"{p.plan_id} {a.label}", a.rationale)); refs.append(("rationale", p, a))
                if a.original and a.plain:
                    items.append((f"{p.plan_id} original idea '{a.label}'", a.plain)); refs.append(("original", p, a))
        for d in drafts.plans:
            for rv in d.request_views:
                txt, _ = AG.strip_numbers(rv.explanation)
                if txt:
                    items.append((f"{d.plan_id} view on {rv.request}", txt)); refs.append(("view", d.plan_id, rv.request))
        for ch in challenges:
            if ch.reason:
                items.append((f"skeptic on {ch.problem}", ch.reason)); refs.append(("skeptic", ch, None))
        plan_txt = "\n".join(f"- {p.plan_id} ({p.variant}): " + "; ".join(f"phase {a.phase} {a.label} for {a.scope}"
                                                                         for a in p.actions) for p in plans)
        rules_txt = "\n".join(f"- {d.intervention_id}: {d.decision} ({d.reason})" for d in leadership)
        facts_txt = (f"{message}\n\nFINAL PLANS:\n{plan_txt}\n\nRULE VERDICTS ON LEADERSHIP REQUESTS:\n{rules_txt}\n\n"
                     + BR.client_facts(G, client))
        texts, rep = await FC.run(items, facts_txt, "fact_checker:plans", calls)
        changed = False
        for (kind, obj, extra), txt in zip(refs, texts):
            if kind == "thesis":
                obj.thesis = txt or vmap[obj.plan_id]["emphasis"]
            elif kind == "rationale":
                extra.rationale = txt or ""
            elif kind == "original" and txt is None:
                obj.actions = [a for a in obj.actions if a is not extra]
                changed = True
            elif kind == "view" and txt is None:
                rejected_views.add((obj, extra))
            elif kind == "skeptic":
                obj.reason = txt or ""
        if changed:
            _score_plans(plans, targets_all, roots, cases, client)
        notes.append(f"layer 1: {len(rep.citations_removed)} citation(s) removed; layer 2: {rep.status}"
                     + (f" on {rep.checker_model}, {rep.checked} sentence(s) checked, {len(rep.removed)} removed" if rep.status == "ran" else ""))
        notes += [f"removed ({x.verdict}) {x.where}: {x.text[:80]} - {x.reason[:100]}" for x in rep.removed]
        if rep.status == "unavailable":
            notes.append(rep.note)
        return rep
    fact_report = await stage("fact_check", "critic", s_fact)

    async def s_jury(calls, notes):
        b = await AG.jury(client, G, plans, roots, calls, priorities_txt)
        notes.append(f"{len(b)} of 5 jurors answered")
        return b
    ballots = await stage("jury", "agent", s_jury)

    def s_jc(calls, notes):
        det = {p.plan_id: p.det_score for p in plans}
        if not ballots:
            notes.append("no juror answered: winner by deterministic score")
            return None
        audit = AG.jury_critic(G, plans, ballots, det)
        notes += audit.flags or ["no flags"]
        return audit
    audit = await stage("jury_critic", "critic", s_jc)
    for p in plans:
        p.jury_score = audit.plan_scores.get(p.plan_id) if audit else None
        p.final = round(0.5 * (p.jury_score or 0) + 0.5 * p.det_score, 4) if audit else p.det_score
    if audit and audit.decided_by == "deterministic_tiebreak":
        top2 = sorted(plans, key=lambda p: -(p.final or 0))[:2]
        winner = max(top2, key=lambda p: (p.det_score, p.plan_id == "P1")).plan_id
    else:
        winner = max(plans, key=lambda p: (p.final or 0, p.det_score, -int(p.plan_id[1:]))).plan_id
    win = next(p for p in plans if p.plan_id == winner)
    leadership = place_requests(client.leadership_requests,
                                [PlanAction(action=a.label, intervention_id=a.action if not a.original else "original",
                                            phase=a.phase, target_scope=a.scope, addresses=a.fixes, evidence=a.evidence)
                                 for a in win.actions], client)
    views = {}
    for rv in next((d.request_views for d in drafts.plans if d.plan_id == winner), []):
        txt, _ = AG.strip_numbers(rv.explanation)
        if (winner, rv.request) in rejected_views:
            continue
        txt, _ = FC.ground_citations(txt) if txt else (txt, [])
        if txt and not any(i.kind == "contradiction" and i.target == rv.request for i in final_issues):
            views[rv.request] = txt
    for d in leadership:                                   # every verdict gets a plain-language explanation
        views.setdefault(d.intervention_id, BR.plain_reason(G, d))
    case_ids = [c.case for c in cases if c.worker_fit and c.score > 0][:3]
    roi, kpis = calculate_roi([a.action if not a.original else "original" for a in win.actions], case_ids, client)
    conf = BR.confidence(G, client, signals, accepted)
    fp = fingerprint(client, fi.effective)
    dec = decisions(accepted, roots, win, leadership, roi)

    def s_stab(calls, notes):
        st = check(fp, dec)
        notes.append("first run for this input" if st.same_as_previous is None else
                     "same answer as the previous run" if st.same_as_previous else "DIFFERENT from the previous run")
        notes += st.differences
        return st
    stability = await stage("stability", "tool", s_stab)
    stab_note = ("This is the first analysis of exactly this input." if stability.same_as_previous is None else
                 f"Asked again with the same data, the engine gave the same answer ({stability.previous_runs} earlier run(s))."
                 if stability.same_as_previous else "Warning: this answer differs from an earlier run on the same data; see the stability panel.")

    async def s_report(calls, notes):
        return await BR.write_brief(G, client, signals, accepted, roots, win, leadership, roi, cases, conf, critic_rounds,
                                    audit, stab_note, calls, notes, audience, ST.focus_sentence(fi))
    brief = await stage("report", "agent", s_report)

    cited = sorted({e.ref for l in roots.links for e in l.evidence if e.kind == "document"}
                   | {e for p in plans for a in p.actions for e in a.evidence + a.precedents}
                   | {c.case for c in cases[:5]} | {"FN4", "FN5", "FN6"})
    docs = {d: documents()[d] for d in cited if d in documents()}
    labels = {n: G.nodes[n].get("label", n) for n in G.nodes if G.nodes[n].get("kind") in
              ("problem", "action", "metric", "case", "snippet", "field_note")}
    result = ResultV2(client=client, problems=signals, diagnoses=diagnoses, challenges=challenges, roots=roots, cases=cases,
                      plans=plans, winner=winner, critic_rounds=critic_rounds, ballots=[b for b, _ in ballots],
                      jury_audit=audit, leadership=leadership, leadership_views=views, roi=roi, kpis=kpis,
                      confidence=conf, brief=brief, stability=stability, documents=docs, labels=labels, trace=trace,
                      focus=fi, audience=audience, protected=BR.protected_list(G, client),
                      degraded=degraded_agents(trace), briefs={audience: brief}, fact_check=fact_report,
                      request={"scenario_code": req.scenario_code} if req.scenario is None else
                      {"scenario": req.scenario, "snapshot": req.snapshot, "overrides": req.overrides})
    (RUNS_DIR / "v2").mkdir(parents=True, exist_ok=True)
    (RUNS_DIR / "v2" / f"{run_id}.json").write_text(result.model_dump_json(indent=1), encoding="utf-8")
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--fresh", action="store_true", help="ignore the LLM cache (tests stability without replay)")
    ap.add_argument("--focus", default="", help="e.g. retention=more,advocacy=less")
    ap.add_argument("--audience", default="board", choices=["hr", "cfo", "board"])
    a = ap.parse_args()
    focus = dict(x.split("=", 1) for x in a.focus.split(",") if "=" in x)
    run_id = f"{a.scenario}_{uuid.uuid4().hex[:6]}"
    r = asyncio.run(run_pipeline_v2(RunRequestV2(scenario_code=a.scenario, focus=focus, audience=a.audience),
                                    run_id=run_id, fresh=a.fresh,
                                    on_stage=lambda n, d: print(("✓ " if d else "… ") + n, flush=True)))
    win = next(p for p in r.plans if p.plan_id == r.winner)
    print(f"\n{r.client.company_name} — {r.brief.headline}")
    for c in r.brief.one_minute:
        print(f"  [{c['title']}] {c['text']}")
    print(f"\nWinner {win.plan_id} ({win.variant}): {win.title}  final={win.final}")
    for ph in (1, 2, 3):
        print(f"  Phase {ph}: " + "; ".join(a.label for a in win.actions if a.phase == ph))
    print(f"Stability: {r.stability.same_as_previous}  writer: {r.brief.writer}")
    for t in r.trace:
        print(f"  {t.stage:12} {t.kind:6} {t.seconds:6.1f}s cached={t.cached} {t.models}")
    print(f"written runs/v2/{run_id}.json")


if __name__ == "__main__":
    main()
