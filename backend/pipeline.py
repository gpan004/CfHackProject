"""Orchestrates the 11 stages and writes the trace. CLI: python -m backend.pipeline --scenario CODE"""
import argparse
import asyncio
import json
import re
import time
import uuid

from . import prompts as P
from .causal import influence_matrix, dematel, root_cause_flags
from .config import (RUNS_DIR, N_CANDIDATE_PLANS, N_JURY_PLANS, JURY_PERSONAS, PERSONA_DESCRIPTIONS, PILLAR_IDS)
from .guardrails import place, place_requests, blocked_reason
from .ingest import client_for, track_a
from .knowledge import K, CATALOG, CONCEPTS, tag_concepts
from .llm import llm_json, LLMError
from . import matching, metrics
from .schemas import (RunRequest, PipelineResult, PillarAnalysis, HypothesisSet, ConfutationSet, CausalMap, MatchRatings,
                      CandidatePlans, JuryVerdict, RootCause, StageTrace, Refutation)

STAGES = ["ingest", "pillar_analysis", "hypotheses", "confutation", "causal_map", "matching",
          "strategy", "guardrails", "jury", "ranking", "metrics"]
PREFIX = {"branding": "BR", "recruiting": "RC", "advocacy": "AD", "retention": "RT"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def field_text(client, ref: str) -> str | None:
    if ref == "narrative":
        return client.narrative
    kind, _, key = ref.partition(".")
    return {"signals": client.signals, "internal": client.internal}.get(kind, {}).get(key)


def verify(ev, client) -> bool:
    if ev.kind == "metric":
        return ev.ref in client.metrics
    text = field_text(client, ev.ref)
    return text is not None and bool(_norm(ev.quote)) and _norm(ev.quote) in _norm(text)


def verified(evs, client):
    return [e for e in evs if verify(e, client)]


async def run_pipeline(req: RunRequest, on_stage=None, run_id: str | None = None) -> PipelineResult:
    run_id = run_id or uuid.uuid4().hex[:10]
    trace: list[StageTrace] = []
    on_stage = on_stage or (lambda name, done: None)

    async def stage(name, fn):
        on_stage(name, False)
        t, calls, notes = time.time(), [], []
        out = await fn(calls, notes)
        trace.append(StageTrace(stage=name, seconds=round(time.time() - t, 2), models=sorted({c["model"] for c in calls}),
                                cached=bool(calls) and all(c["cached"] for c in calls), notes=notes))
        on_stage(name, True)
        return out

    async def call(calls, tier, system, user, schema):
        obj, info = await llm_json(tier, system, user, schema)
        calls.append(info)
        return obj

    A = track_a()
    S = {}  # stage outputs

    # 1 ingest
    async def s_ingest(calls, notes):
        c = client_for(req.scenario_code, req.scenario, req.snapshot, req.overrides)
        notes += [f"archetypes: {c.archetypes}", f"{len(c.metrics)} metrics, {len(c.segments)} segments",
                  f"noise flags: {len(c.noise)}", f"readiness gate open: {c.readiness.gate_open}",
                  f"leadership requests: {c.leadership_requests}"]
        return c
    client = await stage("ingest", s_ingest)

    # 2 pillar analysis
    async def s_pillars(calls, notes):
        async def one(pid):
            spec = K["pillar_inputs"][pid]
            rows = [r for r in client.metrics.values()
                    if r.section in spec["metric_sections"] or r.key in spec.get("extra_metrics", [])]
            user = P.header(client)
            user += "\nPILLAR SIGNALS:\n" + "\n".join(f"[signals.{s}] {client.signals.get(s, '')}" for s in spec["signals"])
            user += "\n\nMETRICS:\n" + P.metric_table(rows)
            if "public_reputation" in spec["metric_sections"]:
                user += "\n\nSEGMENTS:\n" + "\n".join(f"{s.name}: {s.rating} stars, {s.reviews} reviews ({s.flag})" for s in client.segments)
            user += "\n\nINTERNAL CONTEXT:\n" + "\n".join(f"[internal.{k}] {v}" for k, v in client.internal.items())
            user += f"\n\n[narrative] {client.narrative}"
            user += "\n\nIGNORED DATA (never use):\n" + "\n".join(f"- {n.sentence}" for n in client.noise)
            sys = P.PILLAR_AGENT.format(pillar=pid, prefix=PREFIX[pid])
            pa = await call(calls, "local", sys, user, PillarAnalysis)
            pa.pillar = pid
            for i, f in enumerate(pa.findings, 1):
                f.id = f"{PREFIX[pid]}-{i}"
                before = len(f.evidence)
                f.evidence = verified(f.evidence, client)
                if len(f.evidence) < before:
                    notes.append(f"{f.id}: removed {before - len(f.evidence)} unverified evidence item(s)")
            return pa
        return list(await asyncio.gather(*(one(p) for p in PILLAR_IDS)))
    pillar_analyses = await stage("pillar_analysis", s_pillars)
    finding_ids = {f.id for pa in pillar_analyses for f in pa.findings}
    dropped: list[dict] = []

    # 3 hypotheses
    async def s_hyp(calls, notes):
        user = ("PILLAR ANALYSES:\n" + P.dump([p.model_dump() for p in pillar_analyses])
                + "\n\nALLOWED CONCEPT IDS: " + ", ".join(CONCEPTS)
                + "\n\nHEALTHY BASELINES (do not treat as problems):\n" + "\n".join(f"- {h}" for h in client.healthy_baselines)
                + "\n\nVALID METRIC KEYS: " + ", ".join(client.metrics)
                + "\nVALID TEXT REFS: " + ", ".join([f"signals.{k}" for k in client.signals] + [f"internal.{k}" for k in client.internal] + ["narrative"]))
        hs = await call(calls, "remote", P.HYPOTHESES, user, HypothesisSet)
        out = []
        for h in hs.hypotheses:
            h.evidence = verified(h.evidence, client)
            unknown = [f for f in h.supporting_finding_ids if f not in finding_ids]
            h.supporting_finding_ids = [f for f in h.supporting_finding_ids if f in finding_ids]
            if unknown:
                notes.append(f"{h.id}: removed unknown finding ids {unknown}")
            if not h.evidence:
                dropped.append({"id": h.id, "statement": h.statement, "reason": "no verified evidence"})
                continue
            h.concepts = list(dict.fromkeys([c for c in h.concepts if c in CONCEPTS] + tag_concepts(h.statement)))
            out.append(h)
        for i, h in enumerate(out, 1):
            h.id = f"H{i}"
        notes.append(f"{len(out)} hypotheses kept, {len(dropped)} dropped")
        return out
    hypotheses = await stage("hypotheses", s_hyp)
    if not hypotheses:
        raise RuntimeError("no hypothesis survived evidence verification")

    # 4 confutation
    async def s_conf(calls, notes):
        user = ("HYPOTHESES:\n" + P.dump([h.model_dump() for h in hypotheses])
                + "\n\nMETRICS:\n" + P.metric_table(client.metrics.values())
                + "\n\nTEXT FIELDS:\n" + "\n".join([f"[signals.{k}] {v}" for k, v in client.signals.items()]
                                                   + [f"[internal.{k}] {v}" for k, v in client.internal.items()]
                                                   + [f"[narrative] {client.narrative}"])
                + "\n\nHEALTHY BASELINES:\n" + "\n".join(f"- {h}" for h in client.healthy_baselines))
        cs = await call(calls, "local", P.CONFUTATOR, user, ConfutationSet)
        refs = {}
        for r in cs.refutations:
            if r.severity == "critical":
                r.counter_evidence = verified(r.counter_evidence, client)
                if not r.counter_evidence:
                    r.severity = "non_critical"
                    notes.append(f"{r.hypothesis_id}: critical refutation without verifiable counter-evidence -> non_critical")
            refs[r.hypothesis_id] = r
        kept = []
        for h in hypotheses:
            r = refs.get(h.id)
            if r and r.severity == "critical":
                dropped.append({"id": h.id, "statement": h.statement, "reason": f"refuted: {r.reason}"})
                notes.append(f"{h.id} dropped (verified critical refutation)")
            else:
                kept.append(h)
        return kept, list(refs.values())
    hypotheses, refutations = await stage("confutation", s_conf)
    if not hypotheses:
        raise RuntimeError("all hypotheses were refuted")
    ref_by = {r.hypothesis_id: r for r in refutations}

    # 5 causal map + DEMATEL
    async def s_causal(calls, notes):
        user = ("HYPOTHESES:\n" + "\n".join(f"{h.id}: {h.statement} (scope: {h.affected_scope})" for h in hypotheses)
                + "\n\nFIELD NOTES:\n" + "\n".join(f"{f.id} ({f.title}): {f.text}" for f in A["field_notes"]))
        cm = await call(calls, "remote", P.CAUSAL, user, CausalMap)
        ids = [h.id for h in hypotheses]
        edges = [e for e in cm.edges if e.source in ids and e.target in ids and e.source != e.target]
        if len(edges) < len(cm.edges):
            notes.append(f"ignored {len(cm.edges) - len(edges)} edge(s) with unknown ids or self-loops")
        W = influence_matrix(ids, edges)
        _, _, prom, rel = dematel(W)
        roots, weights = root_cause_flags(prom, rel)
        rcs = [RootCause(hypothesis=h, prominence=float(prom[i]), relation=float(rel[i]), weight=weights[i],
                         is_root=roots[i], refutation=ref_by.get(h.id)) for i, h in enumerate(hypotheses)]
        rcs.sort(key=lambda r: (not r.is_root, -r.prominence))
        notes.append("root causes: " + ", ".join(r.hypothesis.id for r in rcs if r.is_root))
        return edges, ids, W.tolist(), rcs
    edges, influence_ids, W, root_causes = await stage("causal_map", s_causal)
    roots = [r for r in root_causes if r.is_root]
    root_ids = {r.hypothesis.id for r in roots}

    # 6 matching
    async def s_match(calls, notes):
        pre = matching.prelim(roots, client, A)
        cand = matching.llm_candidates(roots, pre, A)

        async def rate(rc):
            cs = cand[rc.hypothesis.id]
            if not cs:
                return rc.hypothesis.id, None
            user = (f"ROOT CAUSE {rc.hypothesis.id}: {rc.hypothesis.statement}\nCLIENT WORKFORCE: {client.workforce_target}\n\nCASES:\n"
                    + "\n".join(f"{c.id} | sector: {c.sector_profile} | problem: {c.problem} | interventions: "
                                + "; ".join(s.text for s in c.interventions) for c in cs))
            try:
                return rc.hypothesis.id, await call(calls, "local", P.MATCH_VERIFY, user, MatchRatings)
            except LLMError as e:
                notes.append(f"match verify failed for {rc.hypothesis.id}: {e}")
                return rc.hypothesis.id, None
        ratings = {}
        for hid, mr in await asyncio.gather(*(rate(r) for r in roots)):
            allowed_ids = {c.id for c in cand[hid]}
            for m in (mr.ratings if mr else []):
                if m.case_id in allowed_ids:
                    ratings[(hid, m.case_id)] = m.relevance
        res = matching.finalize(roots, pre, A, ratings)
        names = {c.id: c.name for c in A["cases"]}
        for cid in res["excluded_cases"]:
            notes.append(f"{cid} {names[cid]} excluded: sector contamination blocked")
        if res["excluded_snippets"]:
            notes.append(f"snippets excluded (sector): {res['excluded_snippets']}")
        return res
    M = await stage("matching", s_match)
    case_by = {c.id: c for c in A["cases"]}
    top_case_objs = [case_by[c["id"]] for c in M["top_cases"]]
    known_evidence = {c.id for c in A["cases"]} | {s.id for s in A["snippets"]} | {f.id for f in A["field_notes"]}

    # 7 strategy
    async def s_strategy(calls, notes):
        allowed_items, blocked_items = [], []
        for i in K["interventions"]:
            b = blocked_reason(i, client)
            if b:
                blocked_items.append(f"{i['id']}: BLOCKED ({b[0]}) {b[1]}")
            else:
                allowed_items.append(f"{i['id']} | {i['name']} | {i['type']} | prerequisites any of: "
                                     f"{', '.join(i['prerequisites_any']) or '-'} | needs readiness gate: {i['requires_readiness']}")
        user = (P.header(client)
                + "\nROOT CAUSES (weight):\n" + "\n".join(f"{r.hypothesis.id} ({r.weight:.2f}): {r.hypothesis.statement} [scope: {r.hypothesis.affected_scope}]" for r in roots)
                + "\nSURFACE SYMPTOMS:\n" + "\n".join(f"{r.hypothesis.id}: {r.hypothesis.statement}" for r in root_causes if not r.is_root)
                + "\n\nHEALTHY BASELINES (never touch):\n" + "\n".join(f"- {h}" for h in client.healthy_baselines)
                + "\n\nSEGMENTS:\n" + "\n".join(f"- {s.name}: {s.rating} ({s.flag})" for s in client.segments if s.flag != "normal")
                + f"\n\nREADINESS GATE: {'OPEN' if client.readiness.gate_open else 'CLOSED'}; organic advocacy present: "
                  f"{client.readiness.organic_advocacy_present}\n" + "\n".join(f"- {x}" for x in client.readiness.reasons)
                + "\n\nLEADERSHIP REQUESTS:\n" + client.internal.get("leadership_perceptions_and_requests", "")
                + "\n\nTOP CASES:\n" + "\n".join(
                    f"{c.id} {c.name}: " + " ".join(f"{s.step}. {s.text}" for s in c.interventions)
                    + " | KPI deltas: " + ", ".join(f"{k} {v:+.0%}" for k, v in list(c.kpi_deltas.items())[:8]) for c in top_case_objs)
                + "\n\nTOP RESEARCH SNIPPETS:\n" + "\n".join(f"{s['id']} ({s['source']}): {s['finding']}" for s in M["top_snippets"])
                + "\n\nFIELD NOTES:\n" + "\n".join(f"{f.id} ({f.title}): {f.text}" for f in A["field_notes"])
                + "\n\nALLOWED CATALOG:\n" + "\n".join(allowed_items)
                + "\n\nBLOCKED CATALOG (never use):\n" + "\n".join(blocked_items))
        sys = P.STRATEGY.format(n=N_CANDIDATE_PLANS)

        def clean(cp: CandidatePlans):
            valid, errs = [], []
            for n, p in enumerate(cp.plans, 1):
                for a in p.actions:
                    bad = [x for x in a.addresses if x not in root_ids] + [x for x in a.evidence if x not in known_evidence]
                    if bad:
                        errs.append(f"{p.plan_id}: unknown ids {bad}")
                    a.addresses = [x for x in a.addresses if x in root_ids]
                    a.evidence = [x for x in a.evidence if x in known_evidence]
                if p.actions:
                    p.plan_id = f"P{len(valid) + 1}"
                    valid.append(p)
                else:
                    errs.append(f"plan #{n} has no actions")
            return valid, errs

        cp = await call(calls, "remote", sys, user, CandidatePlans)
        plans, errs = clean(cp)
        notes += errs
        if len(plans) < 3:
            cp = await call(calls, "remote", sys, user + "\n\nYOUR PREVIOUS ANSWER HAD ERRORS:\n" + "\n".join(errs)
                            + f"\nReturn exactly {N_CANDIDATE_PLANS} valid plans.", CandidatePlans)
            plans2, errs2 = clean(cp)
            notes += errs2
            plans = plans2 if len(plans2) > len(plans) else plans
        if not plans:
            raise RuntimeError("strategy generation returned no valid plan")
        return plans
    plans = await stage("strategy", s_strategy)

    # 8 guardrails
    async def s_guard(calls, notes):
        scored = []
        for p in plans:
            kept, decisions = place(p.actions, client)
            sp = metrics.pre_score(p, kept, decisions, root_ids, M["case_score_norm"])
            scored.append(sp)
            notes.append(f"{p.plan_id}: pre_score {sp.pre_score:.3f}, fixes "
                         + str(sum(d.decision in metrics.FIX_DECISIONS for d in decisions)))
        top = sorted(scored, key=lambda s: -s.pre_score)[:N_JURY_PLANS]
        return scored, top
    candidates, top = await stage("guardrails", s_guard)

    # 9 jury
    async def s_jury(calls, notes):
        plans_txt = "\n\n".join(
            f"{sp.plan.plan_id}: {sp.plan.title}\nThesis: {sp.plan.thesis}\n" + "\n".join(
                f"Phase {ph}: " + "; ".join(f"{a.action} ({a.target_scope})" for a in sp.plan.actions if a.phase == ph)
                for ph in (1, 2, 3)) for sp in top)
        base = (P.header(client) + "\nROOT CAUSES:\n" + "\n".join(f"{r.hypothesis.id}: {r.hypothesis.statement}" for r in roots)
                + "\n\nPLANS:\n" + plans_txt)

        async def juror(persona):
            sys = P.JUROR.format(persona=persona, description=PERSONA_DESCRIPTIONS[persona])
            try:
                v = await call(calls, "local", sys, base, JuryVerdict)
                v.persona = persona
                return v
            except LLMError as e:
                notes.append(f"juror {persona} failed: {e}")
                return None
        return [v for v in await asyncio.gather(*(juror(p) for p in JURY_PERSONAS)) if v]
    verdicts = await stage("jury", s_jury)

    # 10 ranking + leadership requests
    async def s_rank(calls, notes):
        ranked = metrics.rank([metrics.apply_jury(sp, verdicts) for sp in top])
        win = ranked[0]
        notes.append(f"winner {win.plan.plan_id} final {win.final:.3f}")
        ld = place_requests(client.leadership_requests, win.plan.actions, client)
        py = {"kept": "adopt", "moved": "defer", "blocked": "reject", "deferred_beyond_plan": "reject"}
        for d in ld:
            syns = CATALOG[d.intervention_id]["synonyms"] + [d.intervention_id, CATALOG[d.intervention_id]["name"].lower()]
            lr = next((r for r in win.plan.leadership_responses if any(s in r.request.lower() for s in syns)), None)
            if lr and lr.decision != py[d.decision]:
                notes.append(f"leadership '{d.intervention_id}': LLM said {lr.decision}, Python says {py[d.decision]} (Python wins)")
        return ranked, ld
    ranked, leadership = await stage("ranking", s_rank)

    # 11 metrics
    async def s_metrics(calls, notes):
        r = metrics.roi(ranked[0].plan.actions, top_case_objs, client)
        k = metrics.kpi_projection(client, top_case_objs)
        notes.append(f"cost €{r.cost_eur:,.0f}, expected benefit €{r.benefit_expected_eur:,.0f}")
        return r, k
    roi, kpis = await stage("metrics", s_metrics)

    result = PipelineResult(
        client=client, pillar_analyses=pillar_analyses, hypotheses=hypotheses, dropped_hypotheses=dropped,
        refutations=refutations, causal_edges=edges, influence_ids=influence_ids, influence_matrix=W,
        root_causes=root_causes, case_alignment=M["case_alignment"], snippet_alignment=M["snippet_alignment"],
        top_cases=M["top_cases"], top_snippets=M["top_snippets"], field_notes=M["field_notes"],
        candidates=candidates, ranked=ranked, leadership_decisions=leadership, roi=roi, kpis=kpis, trace=trace)
    RUNS_DIR.mkdir(exist_ok=True)
    (RUNS_DIR / f"{run_id}.json").write_text(result.model_dump_json(indent=1), encoding="utf-8")
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--overrides")
    a = ap.parse_args()
    ov = json.loads(open(a.overrides, encoding="utf-8").read()) if a.overrides else None
    run_id = f"{a.scenario}_{uuid.uuid4().hex[:6]}"
    r = asyncio.run(run_pipeline(RunRequest(scenario_code=a.scenario, overrides=ov),
                                 on_stage=lambda n, d: print(f"{'✓' if d else '…'} {n}"), run_id=run_id))
    w = r.ranked[0]
    print(f"\n{r.client.company_name} — winner: {w.plan.title} (final {w.final:.3f})")
    for ph in (1, 2, 3):
        print(f"  Phase {ph}: " + "; ".join(a.action for a in w.plan.actions if a.phase == ph))
    print("Root causes: " + " | ".join(rc.hypothesis.statement for rc in r.root_causes if rc.is_root))
    print(f"ROI expected: {r.roi.roi_expected}  payback months: {r.roi.payback_months_expected}")
    for t in r.trace:
        print(f"  {t.stage:16s} {t.seconds:6.1f}s cached={t.cached} {t.models}")
    print(f"written runs/{run_id}.json")


if __name__ == "__main__":
    main()
