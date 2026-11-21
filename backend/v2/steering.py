"""Client steering (deterministic, no AI): priorities per pillar, the instant what-if, and the request checker.

Rule: the client can change PRIORITIES, never FACTS. Focus changes which root causes come first, which ones the focused
plan covers, and how plans are scored. It never changes which problems exist, the evidence, the guardrails or the ROI
arithmetic.
"""
import re

from ..guardrails import place_requests
from ..knowledge import CATALOG
from ..schemas import PlanAction
from .brief import readable
from .kg import facts, label, in_edges, out_edges
from .schemas import (FocusInfo, PriorityRow, PlanDiff, WhatIfResult, RequestCheck, RequestVerdict, RootCauseResult,
                      Source)
from .tools import (load_scenario, check_metrics, find_root_causes, allowed_actions, canonical_plan, schedule_phases,
                    rank_cases, calculate_roi, gate_action, explain_action, check_relevance)

PILLARS = ["branding", "recruiting", "advocacy", "retention"]
MULT = {"less": 0.5, "normal": 1.0, "more": 2.0}
WORD = {"less": "Less", "normal": "Normal", "more": "More"}


def pillar_label(p: str) -> str:
    return facts()["pillars"].get(p, p)


# ---------- priorities ----------
def normalize_focus(focus: dict | None) -> FocusInfo:
    req = {p: (focus or {}).get(p, "normal") if (focus or {}).get(p) in MULT else "normal" for p in PILLARS}
    eff, warnings = dict(req), []
    levels = set(req.values())
    if levels == {"less"}:
        eff = {p: "normal" for p in PILLARS}
        warnings.append("Every pillar is set to Less. Priorities are relative, so nothing can be put ahead of anything "
                        "else, and lowering everything would leave the root causes unaddressed: the result would not be "
                        "effective. The engine therefore uses Normal for all pillars.")
    elif levels == {"more"}:
        eff = {p: "normal" for p in PILLARS}
        warnings.append("Every pillar is set to More. Priorities are relative, so this is the same as Normal everywhere.")
    elif list(req.values()).count("less") == 3:
        keep = next(p for p in PILLARS if req[p] != "less")
        warnings.append(f"Three of four pillars are set to Less: the plan will concentrate on {pillar_label(keep)} only. "
                        "Root causes in the other pillars will be deferred, so the overall result may be much less effective.")
    return FocusInfo(requested=req, effective=eff, warnings=warnings)


def is_neutral(fi: FocusInfo) -> bool:
    return set(fi.effective.values()) == {"normal"}


def _pillar(G, problem: str) -> str:
    return G.nodes[problem]["pillar"]


def apply_focus(G, roots: RootCauseResult, fi: FocusInfo) -> RootCauseResult:
    """Multiplies each root cause's priority by its pillar's focus (Less x0.5, More x2) and renormalises."""
    r = roots.model_copy(deep=True)
    raw = {x.problem: x.weight * MULT[fi.effective.get(_pillar(G, x.problem), "normal")] for x in r.causes}
    tot = sum(raw.values()) or 1.0
    for x in r.causes:
        x.weight = round(raw[x.problem] / tot, 4)
    order = {"root": 0, "standalone": 1, "intermediate": 2, "symptom": 3}
    r.causes.sort(key=lambda x: (order[x.role], -x.weight, x.problem))
    return r


def focused_targets(G, roots: RootCauseResult, fi: FocusInfo) -> tuple[list[str], list[str], list[str]]:
    """Targets of the focused plan: every non-symptom problem, minus those in Less pillars (deferred), plus the
    symptoms of More pillars (treated directly as well). Returns (targets, deferred, added_symptoms)."""
    targets, deferred, added = [], [], []
    for x in roots.causes:
        lvl = fi.effective.get(_pillar(G, x.problem), "normal")
        if x.role == "symptom":
            if lvl == "more":
                targets.append(x.problem); added.append(x.problem)
        elif lvl == "less":
            deferred.append(x.problem)
        else:
            targets.append(x.problem)
    if not targets:                       # never produce an empty plan
        return [x.problem for x in roots.causes if x.role != "symptom"], [], []
    return targets, deferred, added


def focus_warnings(G, roots: RootCauseResult, fi: FocusInfo, deferred: list[str]) -> list[str]:
    """Warns when the client deprioritises the strongest root cause, or steers a pillar that has no confirmed problem."""
    out = []
    top = next((x for x in roots.causes if x.role in ("root", "standalone")), None)   # neutral ranking
    if top and top.problem in deferred:
        out.append(f"You set {pillar_label(_pillar(G, top.problem))} to Less, but '{top.label}' is the highest-priority "
                   "root cause in the evidence. Deferring it may limit the results of the whole plan.")
    present = {_pillar(G, x.problem) for x in roots.causes}
    for p in PILLARS:
        if fi.effective[p] != "normal" and p not in present:
            out.append(f"{pillar_label(p)} has no confirmed problem for this company, so setting it to "
                       f"{WORD[fi.effective[p]]} cannot change the plan.")
    return out


def focus_items(G, c, roots: RootCauseResult, gates: dict, fi: FocusInfo, targets: list[str]) -> list[dict]:
    """The focused plan. Starts from the deterministic cover of the targets, then for every More pillar adds ALL allowed
    actions that fix its problems (deeper investment, not just the minimum) and asks for the earliest phase the rules
    allow. Actions the rules would push beyond Phase 3 are dropped. Deterministic."""
    items = canonical_plan(G, c, roots, gates, targets)
    if is_neutral(fi):
        return items
    more = {p for p in PILLARS if fi.effective[p] == "more"}
    chosen = {i["action"] for i in items}
    for p in sorted(t for t in targets if _pillar(G, t) in more):
        for a in sorted(x for x, _ in in_edges(G, p, "fixes")):
            if a in chosen or not gates[a].allowed:
                continue
            fixes = sorted({q for q, _ in out_edges(G, a, "fixes")} & set(targets))
            ev = sorted({x for x, _ in in_edges(G, a, "used") if check_relevance(G, x, c).relevant
                         and any(q == p for q, _ in out_edges(G, x, "had_problem"))})
            items.append({"action": a, "fixes": fixes, "evidence": ev, "scope": "company-wide", "source": "plan",
                          "rationale": f"Added because you chose More for {pillar_label(_pillar(G, p))}."})
            chosen.add(a)
    for it in items:
        if it["action"] in CATALOG and CATALOG[it["action"]]["pillar"] in more:
            it["phase_hint"] = "earliest"
    sched, _ = schedule_phases(G, c, items)
    kept = {s.action for s in sched}
    return [it for it in items if it["action"] in kept]


def focus_sentence(fi: FocusInfo) -> str:
    more = [pillar_label(p) for p in PILLARS if fi.effective[p] == "more"]
    less = [pillar_label(p) for p in PILLARS if fi.effective[p] == "less"]
    if not more and not less:
        return ""
    parts = []
    if more:
        parts.append("more weight to " + " and ".join(more))
    if less:
        parts.append("less weight to " + " and ".join(less))
    return "At the client's request, the plan gives " + ", and ".join(parts) + "."


# ---------- instant what-if ----------
def _diff(before, after) -> PlanDiff:
    b, a = {x.action: x for x in before}, {x.action: x for x in after}
    return PlanDiff(added=sorted(k for k in a if k not in b), removed=sorted(k for k in b if k not in a),
                    moved=sorted(f"{k}: phase {b[k].phase} -> {a[k].phase}" for k in a if k in b and a[k].phase != b[k].phase))


def what_if(req) -> WhatIfResult:
    """Recomputes the deterministic part of the analysis with the client's priorities and compares it with the neutral
    analysis. No AI calls: takes well under a second."""
    c, G = load_scenario(req.scenario_code, req.scenario, req.snapshot, req.overrides)
    sig = check_metrics(G, c)
    by = {s.problem: s for s in sig}
    ids = [p for p in (req.problems or []) if p in by] or [s.problem for s in sig if s.status == "confirmed"]
    roots = find_root_causes(G, c, [by[p] for p in ids])
    gates = allowed_actions(G, c)
    fi = normalize_focus(req.focus)
    focused = apply_focus(G, roots, fi)
    t_before = [x.problem for x in roots.causes if x.role != "symptom"]
    t_after, deferred, added = focused_targets(G, focused, fi)
    fi.deferred, fi.added_symptoms = deferred, added
    fi.warnings += focus_warnings(G, roots, fi, deferred)

    def plan_and_roi(rc, targets, focus=None):
        items = focus_items(G, c, rc, gates, focus, targets) if focus else canonical_plan(G, c, rc, gates, targets)
        sched, _ = schedule_phases(G, c, items)
        cases = [x.case for x in rank_cases(G, c, rc, sig) if x.worker_fit and x.score > 0][:3]
        roi, _ = calculate_roi([a.action for a in sched], cases, c)
        return sched, roi
    plan_b, roi_b = plan_and_roi(roots, t_before)
    plan_a, roi_a = plan_and_roi(focused, t_after, fi)

    rank_b = {x.problem: i + 1 for i, x in enumerate(roots.causes)}
    rank_a = {x.problem: i + 1 for i, x in enumerate(focused.causes)}
    wb = {x.problem: x.weight for x in roots.causes}
    rows = [PriorityRow(problem=x.problem, label=x.label, pillar=_pillar(G, x.problem), role=x.role,
                        weight_before=wb[x.problem], weight_after=x.weight, rank_before=rank_b[x.problem],
                        rank_after=rank_a[x.problem]) for x in focused.causes]
    unchanged = [f"{label(G, a)}: {g.reason}" + ("" if not g.allowed else f" (not before phase {g.earliest_phase})")
                 for a, g in gates.items() if g.rule != "ok"]
    d = _diff(plan_b, plan_a)
    summary = []
    if is_neutral(fi):
        summary.append("Priorities are neutral: this is the standard analysis.")
    else:
        if deferred:
            summary.append("Deferred by your priorities: " + ", ".join(label(G, p) for p in deferred) + ". They are still "
                           "real problems and stay in the diagnosis.")
        if added:
            summary.append("Also treated directly because you chose More: " + ", ".join(label(G, p) for p in added) + ".")
        if d.added or d.removed or d.moved:
            summary.append(f"Plan changes: {len(d.added)} action(s) added, {len(d.removed)} removed, {len(d.moved)} moved.")
        else:
            summary.append("The plan's actions do not change: your priorities change the order of importance only.")
        present = {_pillar(G, x.problem) for x in roots.causes}
        in_after = {a.action for a in plan_a}
        for p in PILLARS:
            if fi.effective[p] != "more" or p not in present:
                continue
            fixers = {a for x in roots.causes if _pillar(G, x.problem) == p for a, _ in in_edges(G, x.problem, "fixes")}
            allowed = {a for a in fixers if gates[a].allowed}
            if allowed and allowed <= in_after:
                summary.append(f"Every action the rules allow for {pillar_label(p)} is already in the plan, so More raises "
                               "its priority; the full analysis also asks the strategist for an original idea for it.")
        summary.append(f"Cost {roi_b.cost_eur:,.0f} -> {roi_a.cost_eur:,.0f} EUR; expected benefit "
                       f"{roi_b.benefit_expected_eur:,.0f} -> {roi_a.benefit_expected_eur:,.0f} EUR per year.")
    summary.append("Rules your priorities cannot change: workforce fit, protected strengths and the readiness gate.")
    return WhatIfResult(focus=fi, priorities=rows, plan_before=plan_b, plan_after=plan_a, diff=d, roi_before=roi_b,
                        roi_after=roi_a, unchanged_rules=unchanged, summary=summary)


# ---------- request checker ----------
URGENT = re.compile(r"\b(now|today|tomorrow|immediately|asap|right away|this week|first)\b", re.I)


def match_request(text: str) -> list[str]:
    """Deterministic matching of a free-text request to catalog actions. A hit fully inside a longer hit of another
    action is ignored (e.g. 'ambassador' inside 'track ambassador')."""
    t = " " + re.sub(r"\s+", " ", (text or "").lower()) + " "
    kw = {a: v for a, v in facts()["request_keywords"].items() if a in CATALOG}
    for a in kw:
        kw[a] = list(dict.fromkeys(kw[a] + CATALOG[a]["synonyms"] + [CATALOG[a]["name"].lower()]))
    spans = {}
    for a, words in kw.items():
        for w in words:
            for m in re.finditer(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", t):
                spans.setdefault(a, []).append((m.start(), m.end()))
    keep = []
    for a, ss in spans.items():
        others = [s for b, xs in spans.items() if b != a for s in xs]
        if any(not any(o[0] <= s[0] and s[1] <= o[1] and (o[1] - o[0]) > (s[1] - s[0]) for o in others) for s in ss):
            keep.append((min(s[0] for s in ss), a))
    return [a for _, a in sorted(keep)]


def suggest(text: str, n: int = 3) -> list[dict]:
    words = set(re.findall(r"[a-z]{3,}", (text or "").lower()))
    scored = []
    for a, it in CATALOG.items():
        vocab = set(re.findall(r"[a-z]{3,}", " ".join([it["name"], *it["synonyms"], *facts()["request_keywords"].get(a, [])]).lower()))
        s = len(words & vocab)
        if s:
            scored.append((-s, a))
    return [{"action": a, "label": CATALOG[a]["name"]} for _, a in sorted(scored)[:n]]


def check_request(req) -> RequestCheck:
    c, G = load_scenario(req.scenario_code, req.scenario, req.snapshot, req.overrides)
    ids = match_request(req.text)
    if not ids:
        return RequestCheck(text=req.text, understood=False, suggestions=suggest(req.text),
                            note="This request does not match any action the engine knows, so it cannot be evaluated "
                                 "against the evidence. Try one of the suggestions, or name the action more directly.")
    sig = check_metrics(G, c)
    by = {s.problem: s for s in sig}
    probs = [p for p in (req.problems or []) if p in by] or [s.problem for s in sig if s.status == "confirmed"]
    roots = find_root_causes(G, c, [by[p] for p in probs])
    roles = {x.problem: x.role.replace("_", " ") for x in roots.causes}
    if req.plan:
        plan = [PlanAction(action=label(G, p["action"]), intervention_id=p["action"], phase=int(p.get("phase", 1)),
                           target_scope="", addresses=[], evidence=[]) for p in req.plan if p.get("action") in CATALOG]
    else:
        items = canonical_plan(G, c, roots, allowed_actions(G, c), [x.problem for x in roots.causes if x.role != "symptom"])
        sched, _ = schedule_phases(G, c, items)
        plan = [PlanAction(action=a.label, intervention_id=a.action, phase=a.phase, target_scope="", addresses=[],
                           evidence=[]) for a in sched if not a.original]
    in_plan = {p.intervention_id: p.phase for p in plan}
    urgent = bool(URGENT.search(req.text))
    ids_re = re.compile(r"\b(" + "|".join(sorted(CATALOG, key=len, reverse=True)) + r")\b")
    tidy = lambda s: re.sub(r"^deferred to Phase \d: ", "", ids_re.sub(lambda m: label(G, m.group(1)), s or ""))
    out = []
    for a in ids:
        g = gate_action(G, c, a)
        d = place_requests([a], [p for p in plan if p.intervention_id != a], c)[0]
        d.reason = tidy(d.reason)
        name = label(G, a)
        ev = list(g.evidence)
        precedents = sorted(x for x, _ in in_edges(G, a, "used") if check_relevance(G, x, c).relevant)
        if not g.allowed:
            head = {"sector_fit": f"No: {name} does not fit this workforce",
                    "do_not_touch": "No: this is already a strength to protect"}.get(g.rule, f"No: {name}")
            v, why, ph = "no", g.reason, None
        elif a in in_plan:
            v, ph = "already_planned", in_plan[a]
            head, why = f"Already in the plan, in phase {ph}", ("It is scheduled there because it " + d.reason[0].lower()
                                                                + d.reason[1:]) if d.decision == "moved" \
                else "It is part of the recommended plan."
            if urgent and ph > 1:
                head += f": not now, it waits for phase {ph}"
        elif d.decision == "kept":
            v, ph, head, why = "yes_now", 1, ("Yes, it can start now" if urgent else "Yes, it can start in phase 1"), \
                "It passes the workforce-fit, protected-strength, prerequisite and readiness checks."
        elif d.decision == "moved":
            v, ph = "later", d.to_phase
            head = f"Not now: the earliest sensible start is phase {ph}"
            why = d.reason.replace(f"deferred to Phase {ph}: ", "")
        else:
            v, ph, head, why = "no", None, f"Not in this plan: {name}", d.reason
        why = readable(G, why)
        out.append(RequestVerdict(action=a, label=name, plain=G.nodes[a]["plain"], verdict=v, headline=head,
                                  reason=why[0].upper() + why[1:] if why else "", phase=ph, evidence=ev,
                                  paths=explain_action(G, c, a, roles), precedents=precedents))
    return RequestCheck(text=req.text, understood=True, matches=out,
                        note="Verdicts come from the same rules as the plan (workforce fit, protected strengths, "
                             "prerequisites, readiness gate). No AI is involved.")
