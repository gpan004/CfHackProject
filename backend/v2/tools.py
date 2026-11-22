import re

import numpy as np

from ..causal import dematel
from ..guardrails import place, do_not_touch, sector_ok
from ..ingest import client_for, track_a, split_sentences
from ..knowledge import K, CATALOG, CONCEPTS, ASSUMPTIONS, allowed
from ..metrics import roi as _roi, kpi_projection
from ..schemas import PlanAction
from .kg import (client_layer, documents, facts, norm, out_edges, in_edges, label, quote_in_doc)
from .schemas import (Source, QuoteCheck, ConceptHit, Relevance, MetricCheck, ProblemSignal, CauseLink, RootCauseV2,
                      RootCauseResult, Gate, CaseRank, ScheduledAction)

EXCLUDED_TEXT = {"internal.healthy_metrics_and_strengths_not_to_break",   # strengths, not problems
                 "internal.leadership_perceptions_and_requests"}          # requests are handled separately
PHASE_BY_TYPE = {"diagnostic": 1, "structural": 2, "amplification": 3}


# ---------- 1 ----------
def load_scenario(code=None, scenario=None, snapshot=None, overrides=None):
    """Intake + hygiene: parse the company data (noise sentences removed) and build the client layer of the graph."""
    client = client_for(code, scenario, snapshot, overrides)
    return client, client_layer(client)


# ---------- 2 ----------
def client_texts(client, include_excluded=False) -> dict[str, str]:
    out = {f"signals.{k}": v for k, v in client.signals.items()}
    out.update({f"internal.{k}": v for k, v in client.internal.items()})
    out["narrative"] = client.narrative
    return out if include_excluded else {k: v for k, v in out.items() if k not in EXCLUDED_TEXT}


def verify_quote(ref: str, quote: str, client=None) -> QuoteCheck:
    """True only if `quote` appears verbatim (case/space-insensitive) in the referenced source."""
    if not norm(quote):
        return QuoteCheck(ok=False, ref=ref, quote=quote, reason="empty quote")
    if ref in documents():
        ok = quote_in_doc(ref, quote)
        return QuoteCheck(ok=ok, ref=ref, quote=quote, reason="" if ok else f"not found in {ref}")
    if client is not None:
        if ref in client.metrics:
            v = client.metrics[ref].value
            ok = any(f"{v:{f}}" in quote for f in ("g", ".1f", ".2f", ".0f")) or not re.search(r"\d", quote)
            return QuoteCheck(ok=ok, ref=ref, quote=quote, reason="" if ok else f"metric value is {v:g}")
        text = client_texts(client, include_excluded=True).get(ref)
        if text is not None:
            ok = norm(quote) in norm(text)
            return QuoteCheck(ok=ok, ref=ref, quote=quote, reason="" if ok else f"not found verbatim in {ref}")
    return QuoteCheck(ok=False, ref=ref, quote=quote, reason=f"unknown source {ref}")


# ---------- 3 ----------
def map_concept(text: str, client_archetypes: list[str] | None = None) -> list[ConceptHit]:
    """Deterministic synonym matching against the 18 problem concepts (respecting their worker-type scope)."""
    t, gl, hits = (text or "").lower(), facts()["glossary"]["problems"], []
    removed = facts().get("synonym_overrides", {}).get("remove", {})
    for c in K["concepts"]:
        syn = next((s for s in c["synonyms"] if s in t and s not in removed.get(c["id"], [])), None)
        if syn and (client_archetypes is None or allowed(c["archetype_scope"], client_archetypes)):
            hits.append(ConceptHit(concept=c["id"], synonym=syn, label=gl[c["id"]][0]))
    return hits


# ---------- 4 ----------
def check_relevance(G, item: str, client) -> Relevance:
    """Does an action / case / snippet / problem fit this client's workforce? Answered from the graph."""
    kind, arch = G.nodes[item]["kind"], set(client.archetypes)
    if kind == "action":
        fits = {w for w, _ in out_edges(G, item, "fits")}
        ok = bool(fits & arch)
        return Relevance(item=item, kind=kind, relevant=ok, path=[f"{item} -fits-> {w}" for w in sorted(fits & arch)],
                         reason="fits the client's workforce" if ok else f"only fits {', '.join(sorted(fits))} (FN6)")
    if kind == "case":
        ws = {w for w, _ in out_edges(G, item, "workers")}
        ok = bool(ws & arch)
        return Relevance(item=item, kind=kind, relevant=ok, path=[f"{item} -workers-> {w}" for w in sorted(ws)],
                         reason="same type of workforce" if ok else f"different workforce ({', '.join(sorted(ws))}) (FN6)")
    if kind == "snippet":
        ws = {w for w, _ in out_edges(G, item, "scope")}
        ok = not ws or bool(ws & arch)
        return Relevance(item=item, kind=kind, relevant=ok, path=[f"{item} -scope-> {w}" for w in sorted(ws)],
                         reason="applies to all workforces" if not ws else "applies to this workforce" if ok
                         else f"only about {', '.join(sorted(ws))}")
    if kind == "problem":
        scope = G.nodes[item]["scope"]
        ok = allowed(scope, client.archetypes)
        return Relevance(item=item, kind=kind, relevant=ok, reason="relevant" if ok else f"only relevant for {', '.join(scope)} (FN6)")
    return Relevance(item=item, kind=kind, relevant=True, reason="no scope restriction")


# ---------- 5 ----------
def _metric_check(G, client, key) -> MetricCheck | None:
    r = client.metrics.get(key)
    if r is None:
        return None
    unit = G.nodes[key].get("unit", "") if key in G else ""
    gap = None
    if r.peer not in (None, 0):
        gap = (r.value - r.peer) / abs(r.peer)
        if "lower is better" in unit or key.split(".")[-1] in K["metric_rules"]["lower_is_better"]:
            gap = -gap
        gap = -gap  # positive = worse than peers
    return MetricCheck(key=key, label=label(G, key), unit=unit, value=r.value, peer=r.peer, status=r.status,
                       gap_pct=None if gap is None else round(gap, 4))


def _crossed(op, v, t):
    return {">": v > t, ">=": v >= t, "<": v < t, "<=": v <= t}[op]


def check_metrics(G, client) -> list[ProblemSignal]:
    """Compares every problem's indicator metrics with the sector peers and the research thresholds, and collects
    verbatim client sentences that mention it. Deterministic; sorted by severity then id."""
    gl, assets, out = facts()["glossary"]["problems"], set(facts()["assets"]), []
    texts = client_texts(client)
    for pid in sorted(CONCEPTS):
        if pid in assets:
            continue
        node = G.nodes[pid]
        lab, plain = gl[pid]
        sig = ProblemSignal(problem=pid, label=lab, plain=plain, pillar=node["pillar"])
        if not allowed(node["scope"], client.archetypes):
            continue
        for m, _ in out_edges(G, pid, "indicated_by"):
            mc = _metric_check(G, client, m)
            if mc is None:
                continue
            if mc.status == "worse":
                sig.measured.append(mc)
            elif mc.status == "better":
                sig.healthy.append(mc)
        # research thresholds attached to this problem
        for doc, m, d in [(u, v, d) for u, v, d in G.edges(data=True) if d["rel"] == "threshold_for" and d["problem"] == pid]:
            if d["scope"] != "all" and not set(d["scope"]) & set(client.archetypes):
                continue
            mc = _metric_check(G, client, m)
            if mc and _crossed(d["op"], mc.value, d["value"]):
                mc.thresholds.append(f"{mc.label} is {mc.value:g}, over the {d['op']}{d['value']:g} threshold: {d['meaning']} [{doc}]")
                existing = next((x for x in sig.measured if x.key == m), None)
                if existing:
                    existing.thresholds += mc.thresholds
                else:
                    sig.measured.append(mc)
                    sig.healthy = [h for h in sig.healthy if h.key != m]
        for ref, text in texts.items():
            for sent in split_sentences(text):
                if any(h.concept == pid for h in map_concept(sent, client.archetypes)):
                    sig.text.append(Source(kind="client_text", ref=ref, quote=sent))
        if not (sig.measured or sig.healthy or sig.text):
            continue
        gaps = [min(1.0, max(0.0, x.gap_pct)) for x in sig.measured if x.gap_pct is not None]
        sev = (sum(gaps) / len(gaps) if gaps else 0.3 if sig.measured else 0.0)
        sev += 0.25 * sum(bool(x.thresholds) for x in sig.measured)
        if sig.measured:
            sig.status, sig.reason = "confirmed", f"{len(sig.measured)} indicator(s) worse than peers or over a research threshold"
        elif sig.healthy:
            sig.status, sig.reason = "healthy", "its indicators are better than peers: a strength to protect"
            sev = 0.0
        else:
            sig.status, sig.reason = "text_only", "mentioned in the client's own text, no benchmark metric"
            sev = 0.2
        sig.severity = round(min(1.0, sev), 4)
        out.append(sig)
    return sorted(out, key=lambda s: (-s.severity, s.problem))


# ---------- 6 ----------
FWD = (" forcing ", " leads to ", " leading to ", " drives ", " causing ", " resulting in ", " triggers ")
BACK = (" driven by ", " due to ", " because of ", " because ", " caused by ")


def client_causal_links(client, problems: set[str]) -> list[CauseLink]:
    """Cause->effect links stated in the client's own sentences ("Because of X, Y", "X, forcing Y"). Labelled client_text."""
    links = {}
    for ref, text in client_texts(client).items():
        for sent in split_sentences(text):
            low = " " + sent.lower() + " "
            pairs = []
            if low.strip().startswith("because") and "," in sent:
                head, tail = sent.split(",", 1)
                pairs.append((head, tail))
            for cue in FWD:
                if cue in low:
                    i = low.index(cue)
                    pairs.append((low[:i], low[i + len(cue):]))
            for cue in BACK:
                if cue in low and not low.strip().startswith("because"):
                    i = low.index(cue)
                    pairs.append((low[i + len(cue):], low[:i]))
            for cause_txt, effect_txt in pairs:
                cs = {h.concept for h in map_concept(cause_txt, client.archetypes)} & problems
                es = {h.concept for h in map_concept(effect_txt, client.archetypes)} & problems
                for c in sorted(cs):
                    for e in sorted(es - {c}):
                        links.setdefault((c, e), CauseLink(
                            source=c, target=e, strength=1, origin="client_text",
                            mechanism="stated in the client's own data",
                            evidence=[Source(kind="client_text", ref=ref, quote=sent)]))
    return [links[k] for k in sorted(links)]


def find_root_causes(G, client, problems: list[ProblemSignal]) -> RootCauseResult:
    """Builds the cause-effect sub-graph of the confirmed problems from the REFERENCE links (dataset evidence) plus
    links stated in the client's own text, then runs DEMATEL. No LLM-made links."""
    ids = sorted(p.problem for p in problems)
    sev = {p.problem: p.severity for p in problems}
    links = []
    for u in ids:
        for v, d in out_edges(G, u, "causes"):
            if v in ids and (d["scope"] == "all" or set(d["scope"]) & set(client.archetypes)):
                links.append(CauseLink(source=u, target=v, strength=d["strength"], mechanism=d["mechanism"],
                                       origin="reference", evidence=[Source(**e) for e in d["evidence"]]))
    known = {(l.source, l.target) for l in links}
    links += [l for l in client_causal_links(client, set(ids)) if (l.source, l.target) not in known]
    idx = {p: i for i, p in enumerate(ids)}
    W = np.zeros((len(ids), len(ids)))
    for l in links:
        W[idx[l.source], idx[l.target]] = max(W[idx[l.source], idx[l.target]], l.strength / 3.0)
    r, c, prom, rel = dematel(W) if len(ids) else (np.zeros(0),) * 4
    gl = facts()["glossary"]["problems"]
    out = []
    for p in ids:
        i = idx[p]
        outs, ins = [l.target for l in links if l.source == p], [l.source for l in links if l.target == p]
        if not outs and not ins:
            role = "standalone"
        elif not ins:
            role = "root"
        elif not outs:
            role = "symptom"
        else:
            role = "root" if rel[i] > 1e-9 else "intermediate"
        out.append(RootCauseV2(problem=p, label=gl[p][0], plain=gl[p][1], role=role, drives=float(r[i]),
                               driven_by=float(c[i]), prominence=float(prom[i]), relation=float(rel[i]), weight=0.0,
                               causes=sorted(outs), caused_by=sorted(ins)))
    # priority weight: how much a problem drives others (prominence) times how bad it is here (severity)
    targets = [x for x in out if x.role in ("root", "standalone")]
    raw = {x.problem: (x.prominence if x.prominence > 0 else 1.0) * (0.5 + sev.get(x.problem, 0)) for x in targets}
    tot = sum(raw.values()) or 1.0
    for x in out:
        x.weight = round(raw.get(x.problem, 0.0) / tot, 4)
    order = {"root": 0, "standalone": 1, "intermediate": 2, "symptom": 3}
    out.sort(key=lambda x: (order[x.role], -x.weight, x.problem))
    return RootCauseResult(ids=ids, matrix=W.round(4).tolist(), links=links, causes=out)


# ---------- 7 ----------
def gate_action(G, client, action: str) -> Gate:
    """Can this action be used for this client, and from which phase? Rules: workforce fit (FN6), do-not-touch healthy
    baselines (FN5), readiness gate (FN4/R5). Same rules as the v1 guardrails, explained from the graph."""
    item = CATALOG[action]
    if not sector_ok(item, client.archetypes):
        rel = check_relevance(G, action, client)
        return Gate(action=action, allowed=False, rule="sector_fit", reason=f"{label(G, action)} {rel.reason}",
                    evidence=[Source(kind="document", ref="FN6", quote="Interventions only generate ROI when matched to the physical and operational reality of the workforce.")])
    if do_not_touch(item, client.metrics):
        ms = "; ".join(f"{label(G, k)} {client.metrics[k].value:g} vs peer {client.metrics[k].peer:g}"
                       for k in item["target_metrics"] if k in client.metrics and client.metrics[k].status == "better")
        return Gate(action=action, allowed=False, rule="do_not_touch",
                    reason=f"it targets something that is already better than peers ({ms}); changing it wastes budget",
                    evidence=[Source(kind="document", ref="FN5", quote="re-engineering those healthy foundations wastes budget and delays high-leverage fixes")])
    if item["requires_readiness"]:
        r = client.readiness
        cond = G.nodes["readiness_gate"]
        ev = [Source(**e) for e in cond["evidence"]]
        if not r.gate_open:
            why = "; ".join(x for x in r.reasons if not x.startswith("Organic"))
            return Gate(action=action, allowed=True, earliest_phase=3, rule="readiness_gate",
                        reason=f"waits for internal trust to be fixed first ({why})", evidence=ev)
        if not r.organic_advocacy_present:
            return Gate(action=action, allowed=True, earliest_phase=2, rule="readiness_gate",
                        reason="trust is fine but there is no organic advocacy base yet", evidence=ev)
    return Gate(action=action, allowed=True, earliest_phase=1, rule="ok", reason="passes workforce fit, healthy-baseline and readiness checks")


# ---------- 8 ----------
def _why_now(G, a: PlanAction, d) -> str:
    if d is not None and d.decision in ("moved", "added") or (d is not None and d.rule not in ("ok", "original_unvalidated")):
        return d.reason[0].upper() + d.reason[1:] if d.reason else ""
    t = G.nodes[a.intervention_id]["type"] if a.intervention_id in G else "original"
    return {"diagnostic": "Diagnose first: measure before changing anything (FN5).",
            "structural": "Structural fix, built on the diagnostics.",
            "amplification": "Amplify only what already works (FN4).",
            "original": "New idea proposed for this client."}.get(t, "")


def _initial_phases(G, client, items: list[dict]) -> dict[str, int]:
    """Earliest sensible phase per catalog action: max(type phase, readiness-gate phase), then make sure every action
    comes after one of its prerequisites. If that would push past Phase 3, pull the prerequisite earlier instead
    (as long as its own gate allows it). The guardrails (place) still validate the result."""
    ids = [it["action"] for it in items if it["action"] in CATALOG]
    gate = {a: gate_action(G, client, a).earliest_phase for a in ids}
    earliest = {it["action"] for it in items if it.get("phase_hint") == "earliest"}   # client chose More for its pillar
    ph = {a: gate[a] if a in earliest else max(PHASE_BY_TYPE.get(CATALOG[a]["type"], 2), gate[a]) for a in ids}
    for _ in range(6):
        changed = False
        for a in ids:
            pres = [p for p in CATALOG[a]["prerequisites_any"] if p in ph]
            if not pres:
                continue
            p = min(pres, key=lambda x: (ph[x], x))
            if ph[p] < ph[a]:
                continue
            if ph[p] + 1 <= 3:
                ph[a], changed = ph[p] + 1, True
            elif gate[p] <= 2:
                ph[p], ph[a], changed = 2, 3, True
        if not changed:
            break
    return ph


def schedule_phases(G, client, items: list[dict]) -> tuple[list[ScheduledAction], list]:
    """items: [{action, scope, fixes, evidence, source, original?, title?, description?, phase?}].
    Python decides phases: starting phase by action type and readiness gate, prerequisites (needs_first) first.
    The v1 guardrails then validate and correct. Returns (scheduled actions, guardrail decisions)."""
    acts, srcs = [], []
    init = _initial_phases(G, client, items)
    for it in items:
        aid = it["action"]
        phase = init.get(aid) or it.get("phase") or 2
        acts.append(PlanAction(action=it.get("title") or label(G, aid), intervention_id=aid if aid in CATALOG else "original",
                               phase=phase, target_scope=it.get("scope") or "company-wide",
                               addresses=list(it.get("fixes", [])), evidence=list(it.get("evidence", []))))
        srcs.append("plan" if it.get("source", "plan") not in ("plan", "leadership_request", "auto_added") else it.get("source", "plan"))
    kept, decisions = place(acts, client, srcs)
    by_subject = {}
    for d in decisions:
        by_subject.setdefault(d.subject, d)
    meta = {(it.get("title") or label(G, it["action"])): it for it in items}
    out = []
    for a in kept:
        d = by_subject.get(a.action)
        it = meta.get(a.action, {})
        aid = a.intervention_id
        orig = aid == "original"
        precedents = sorted({u for u, _ in in_edges(G, aid, "used") if check_relevance(G, u, client).relevant}) if not orig else []
        added = d is not None and d.decision == "added"
        own_fixes = sorted(p for p, _ in out_edges(G, aid, "fixes")) if not orig else []
        out.append(ScheduledAction(
            action=aid if not orig else f"original:{a.action}", label=a.action,
            plain=G.nodes[aid]["plain"] if not orig else it.get("description", ""), phase=a.phase, scope=a.target_scope,
            fixes=own_fixes if added else (a.addresses or own_fixes),   # an auto-added prerequisite fixes what IT fixes
            why_now=_why_now(G, a, d), evidence=a.evidence, precedents=precedents, original=orig,
            source="auto_added" if added else it.get("source", "plan")))
    out.sort(key=lambda x: (x.phase, 0 if not x.original else 1, x.action))
    return out, decisions


# ---------- 9 ----------
def rank_cases(G, client, roots: RootCauseResult, signals: list[ProblemSignal]) -> list[CaseRank]:
    """Precedent search on the graph: cases with the same workforce that HAD the client's problems and USED actions that
    fix them. Score = 0.6 problem overlap (weighted) + 0.4 action overlap. Deterministic; ties broken by id."""
    w = {x.problem: max(x.weight, 0.05) for x in roots.causes}
    probs = set(w)
    fixers = {a for p in probs for a, _ in in_edges(G, p, "fixes")}
    out = []
    for case in sorted(n for n, d in G.nodes(data=True) if d.get("kind") == "case"):
        had = {p for p, _ in out_edges(G, case, "had_problem")}
        used = {a for a, _ in out_edges(G, case, "used")}
        rel = check_relevance(G, case, client)
        shared_p, shared_a = sorted(had & probs), sorted(used & fixers)
        pscore = sum(w[p] for p in shared_p) / (sum(w.values()) or 1)
        ascore = len(shared_a) / (len(fixers) or 1)
        score = (0.6 * pscore + 0.4 * ascore) * (1.0 if rel.relevant else 0.0)
        out.append(CaseRank(case=case, name=label(G, case), score=round(score, 4), shared_problems=shared_p,
                            shared_actions=shared_a, worker_fit=rel.relevant, outcome=G.nodes[case]["outcome"],
                            reason=(f"same workforce; had {', '.join(label(G, p) for p in shared_p) or 'no shared problem'}; "
                                    f"used {', '.join(label(G, a) for a in shared_a) or 'no shared action'}")
                            if rel.relevant else f"excluded: {rel.reason}"))
    return sorted(out, key=lambda c: (-c.score, c.case))


# ---------- 10 ----------
def calculate_roi(action_ids: list[str], case_ids: list[str], client):
    """Wraps the v1 ROI arithmetic (precedent deltas x client base values; costs from data/assumptions.json)."""
    by = {c.id: c for c in track_a()["cases"]}
    cases = [by[c] for c in case_ids if c in by]
    acts = [PlanAction(action=a, intervention_id=a if a in CATALOG else "original", phase=1, target_scope="",
                       addresses=[], evidence=[]) for a in action_ids]
    return _roi(acts, cases, client), kpi_projection(client, cases)


# ---------- helpers built on the tools ----------
def action_cost(aid: str) -> float:
    return ASSUMPTIONS["unit_cost_eur"].get(aid, ASSUMPTIONS["original_action_cost_eur"])


def allowed_actions(G, client) -> dict[str, Gate]:
    return {a: gate_action(G, client, a) for a in sorted(CATALOG)}


def precedent_support(G, client, action: str, problem: str) -> list[str]:
    """Cases with the same workforce that had `problem` and used `action`."""
    return sorted(c for c, _ in in_edges(G, action, "used")
                  if check_relevance(G, c, client).relevant and any(p == problem for p, _ in out_edges(G, c, "had_problem")))


def canonical_plan(G, client, roots: RootCauseResult, gates: dict[str, Gate], targets: list[str],
                   budget_mode: bool = False) -> list[dict]:
    """Deterministic greedy cover: for every target problem pick the allowed action that fixes the most targets, with the
    most same-workforce precedents (or the lowest cost in budget mode). Ties broken by id. Same input -> same plan."""
    infeasible: set[str] = set()
    for _ in range(len(gates)):
        chosen = _greedy_cover(G, client, gates, targets, budget_mode, infeasible)
        items = _plan_items(G, client, chosen, targets)
        sched, decisions = schedule_phases(G, client, items)
        kept = {s.action for s in sched}
        lost = [a for a in chosen if a not in kept]      # blocked or deferred beyond Phase 3 by the guardrails
        if not lost:
            return items
        infeasible |= set(lost)
    return items


def _greedy_cover(G, client, gates, targets, budget_mode, infeasible) -> list[str]:
    """Pass 1 covers problems with real fixes (structural / amplification); pass 2 uses a diagnostic only for problems
    nothing else can fix. Diagnostics still enter the plan as prerequisites of the fixes (needs_first)."""
    chosen: list[str] = []
    remaining = _cover(G, client, gates, list(targets), budget_mode, infeasible, chosen, diagnostics=False)
    _cover(G, client, gates, remaining, budget_mode, infeasible, chosen, diagnostics=True)
    return chosen


def _cover(G, client, gates, remaining, budget_mode, infeasible, chosen, diagnostics) -> list[str]:
    while remaining:
        best = None
        for a, g in gates.items():
            if not g.allowed or a in chosen or a in infeasible:
                continue
            if (CATALOG[a]["type"] == "diagnostic") != diagnostics:
                continue
            covers = sorted({p for p, _ in out_edges(G, a, "fixes")} & set(remaining))
            if not covers:
                continue
            support = sum(len(precedent_support(G, client, a, p)) for p in covers)
            key = ((len(covers), -action_cost(a), support) if budget_mode else (len(covers), support, -action_cost(a)))
            if best is None or key > best[0] or (key == best[0] and a < best[1]):
                best = (key, a, covers)
        if best is None:
            break
        chosen.append(best[1])
        remaining = [p for p in remaining if p not in best[2]]
    return remaining


def _plan_items(G, client, chosen: list[str], targets: list[str]) -> list[dict]:
    out = []
    for a in chosen:
        fixes = sorted({p for p, _ in out_edges(G, a, "fixes")} & set(targets))
        ev = sorted({c for p in fixes for c in precedent_support(G, client, a, p)} |
                    {d["evidence"][0]["ref"] for _, d in out_edges(G, a, "effect_on")
                     if d["scope"] == "all" or set(d["scope"]) & set(client.archetypes)})
        out.append({"action": a, "fixes": fixes, "evidence": ev, "scope": "company-wide", "source": "plan"})
    return out


def explain_action(G, client, action: str, problems: dict) -> list[str]:
    """Human-readable evidence paths for one action, e.g. 'Manager coaching -> fixes -> Weak middle management (root cause)
    <- had_problem <- C05 Alfa Group (outcome: ...)'."""
    if action not in G:
        return []
    paths = []
    for p, _ in out_edges(G, action, "fixes"):
        if p not in problems:
            continue
        line = f"{label(G, action)} → fixes → {label(G, p)} ({problems[p]})"
        cases = precedent_support(G, client, action, p)
        if cases:
            line += " · proven in " + ", ".join(f"{c} {label(G, c).split(' (')[0]}" for c in cases)
        paths.append(line)
    for m, d in out_edges(G, action, "effect_on"):
        if d["scope"] == "all" or set(d["scope"]) & set(client.archetypes):
            paths.append(f"{label(G, action)} → research effect → {label(G, m)}: \"{d['evidence'][0]['quote']}\" [{d['evidence'][0]['ref']}]")
    return paths
