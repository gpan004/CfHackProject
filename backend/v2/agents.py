"""The v2 agents. Each agent is: build a message from TOOL results -> LLM -> Python verification.
Agents can choose among given ids, quote verbatim text and explain; they never decide numbers, phases or verdicts.

Diagnostician (x pillars) -> Skeptic -> Strategist <-> Plan critic (loop) -> Jury -> Jury critic -> Report writer
"""
import asyncio
import re
from statistics import median

from ..config import JURY_PERSONAS, PERSONA_DESCRIPTIONS
from ..knowledge import CATALOG, CONCEPTS
from . import prompts as P
from .kg import documents, label
from .llm import call
from .schemas import (Diagnosis, SkepticReport, StrategyDrafts, CriticReview, CriticIssue, JurorBallot, JuryAudit,
                      ProblemView, Challenge, Quote)
from .tools import verify_quote, check_relevance

ID_RE = re.compile(r"\b(?:C\d{2}|R\d{1,2}|FN\d)\b")
PILLAR_GROUPS = {"branding": ["branding"], "recruiting": ["recruiting"], "advocacy": ["advocacy", "cross"],
                 "retention": ["retention"]}
JUROR_TIER = {"Board Member": "remote", "HR Manager": "local", "CFO": "remote",
              "Employee in the affected cohort": "local", "Potential Candidate from the target workforce": "local"}


# ---------- shared verification helpers ----------
def strip_numbers(text: str) -> tuple[str, list[str]]:
    """Removes sentences that contain digits outside document ids. Returns (clean text, removed sentences)."""
    keep, removed = [], []
    for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()):
        if not s:
            continue
        (removed if re.search(r"\d", ID_RE.sub("", s)) else keep).append(s)
    return " ".join(keep), removed


def verify_scope(scope: str, client) -> tuple[str, bool]:
    """A scope is accepted if it is company-wide or every capitalised word in it appears in the client's data."""
    s = (scope or "").strip()
    if not s or s.lower().startswith("company"):
        return "company-wide", True
    corpus = " ".join([client.narrative, client.workforce_target, *client.signals.values(), *client.internal.values(),
                       *[x.name.replace("_", " ") for x in client.segments]]).lower()
    words = [w for w in re.findall(r"[A-Z][A-Za-z\-]{2,}", s)]
    ok = all(w.lower() in corpus for w in words)
    return (s if ok else "company-wide"), ok


def _quotes_ok(quotes: list[Quote], client) -> tuple[list[Quote], list[str]]:
    good, bad = [], []
    for q in quotes:
        (good if verify_quote(q.ref, q.quote, client).ok else bad).append(q)
    return good, [f"{q.ref}: {q.quote[:60]}" for q in bad]


def _header(c) -> str:
    return (f"COMPANY: {c.company_name}\nINDUSTRY: {c.industry}\nWORKFORCE: {c.workforce_target}\n"
            f"WORKER TYPES: {', '.join(c.archetypes) or 'unknown'}\n")


def _metric_line(m) -> str:
    peer = "no benchmark" if m.peer is None else f"peer {m.peer:g}"
    gap = "" if m.gap_pct is None else f", {abs(m.gap_pct) * 100:.0f}% {'worse' if m.gap_pct > 0 else 'better'}"
    th = "".join(f"\n      threshold: {t}" for t in m.thresholds)
    return f"    - {m.label} ({m.key}): {m.value:g} vs {peer}{gap}{th}"


# ---------- 1 Diagnostician (one per pillar, local) ----------
async def diagnose(client, signals, trace_calls) -> tuple[list[Diagnosis], dict, list[str]]:
    """Returns (diagnoses, accepted {problem_id: {'contested': bool, 'scope': str, 'explanation': str}}, notes)."""
    notes, accepted, diagnoses = [], {}, []
    cands = [s for s in signals if s.status in ("confirmed", "text_only")]
    segs = "\n".join(f"- {s.name.replace('_', ' ')}: {s.rating} stars ({s.flag})" for s in client.segments) or "- none"

    async def one(pillar):
        mine = [s for s in cands if s.pillar in PILLAR_GROUPS[pillar]]
        if not mine:
            return pillar, None, mine
        lines = []
        for s in mine:
            lines.append(f"* {s.problem}: {s.label} - {s.plain}\n  status: {s.status} ({s.reason})")
            if s.measured:
                lines.append("  metrics worse than peers / over threshold:\n" + "\n".join(_metric_line(m) for m in s.measured))
            if s.healthy:
                lines.append("  metrics better than peers:\n" + "\n".join(_metric_line(m) for m in s.healthy))
            for t in s.text[:4]:
                lines.append(f"  client sentence [{t.ref}]: \"{t.quote}\"")
        user = (_header(client) + "\nCANDIDATE PROBLEMS:\n" + "\n".join(lines) + f"\n\nSITES / SEGMENTS:\n{segs}\n\n"
                f"COHORTS (internal.cohort_and_site_asymmetries): {client.internal.get('cohort_and_site_asymmetries', 'n/a')}")
        obj, info = await call(f"diagnostician:{pillar}", "local", P.DIAGNOSTICIAN.format(pillar=pillar), user, Diagnosis)
        trace_calls.append(info)
        return pillar, obj, mine

    for pillar, obj, mine in await asyncio.gather(*(one(p) for p in PILLAR_GROUPS)):
        if obj is None:
            continue
        ids = {s.problem for s in mine}
        views = {}
        for v in obj.problems:
            if v.problem not in ids:
                notes.append(f"{pillar}: ignored unknown problem id '{v.problem}'")
                continue
            v.quotes, bad = _quotes_ok(v.quotes, client)
            notes += [f"{v.problem}: removed unverifiable quote ({b})" for b in bad]
            v.scope, scope_ok = verify_scope(v.scope, client)
            if not scope_ok:
                notes.append(f"{v.problem}: scope not found in the client data -> company-wide")
            v.explanation, removed = strip_numbers(v.explanation)
            notes += [f"{v.problem}: removed sentence with a number: {r[:60]}" for r in removed]
            views[v.problem] = v
        for s in mine:
            v = views.get(s.problem)
            if s.status == "confirmed":
                contested = v is not None and not v.agree
                if contested:
                    notes.append(f"{s.problem}: diagnostician disagreed, but metrics confirm it -> kept as contested")
                accepted[s.problem] = {"contested": contested, "scope": v.scope if v else "company-wide",
                                       "explanation": (v.explanation if v and v.explanation else s.plain)}
            elif v is not None and v.agree and (v.quotes or s.text):
                accepted[s.problem] = {"contested": False, "scope": v.scope, "explanation": v.explanation or s.plain}
            else:
                notes.append(f"{s.problem}: text-only signal not confirmed by the diagnostician -> not used")
        obj.problems = list(views.values())
        diagnoses.append(obj)
    return diagnoses, accepted, notes


# ---------- 2 Skeptic (local) ----------
async def challenge(client, signals, accepted: dict, trace_calls) -> tuple[list[Challenge], dict, list[str]]:
    notes, by = [], {s.problem: s for s in signals}
    if not accepted:
        return [], accepted, notes
    lines = []
    for pid in sorted(accepted):
        s = by[pid]
        lines.append(f"* {pid}: {s.label} - {accepted[pid]['explanation']}")
        lines += [_metric_line(m) for m in s.measured]
    healthy = "\n".join(f"- {h}" for h in client.healthy_baselines) or "- none"
    texts = "\n".join(f"[{k}] {v}" for k, v in [*((f"signals.{k}", v) for k, v in client.signals.items()),
                                                *((f"internal.{k}", v) for k, v in client.internal.items()),
                                                ("narrative", client.narrative)])
    user = (_header(client) + "\nDIAGNOSED PROBLEMS:\n" + "\n".join(lines) + f"\n\nHEALTHY BASELINES:\n{healthy}\n\n"
            f"CLIENT TEXT (quote from here, with the ref in brackets):\n{texts}")
    obj, info = await call("skeptic", "local", P.SKEPTIC, user, SkepticReport)
    trace_calls.append(info)
    out = []
    for ch in obj.challenges:
        if ch.problem not in accepted:
            continue
        ch.counter_quotes, bad = _quotes_ok(ch.counter_quotes, client)
        notes += [f"{ch.problem}: removed unverifiable counter-quote ({b})" for b in bad]
        ch.reason, _ = strip_numbers(ch.reason)
        if ch.verdict == "refuted" and not ch.counter_quotes:
            ch.verdict = "weaker"
            notes.append(f"{ch.problem}: refutation without verifiable counter-evidence -> downgraded to 'weaker'")
        if ch.verdict == "refuted":
            if by[ch.problem].status == "text_only":
                accepted.pop(ch.problem)
                notes.append(f"{ch.problem}: refuted with verified counter-evidence -> removed")
            else:
                accepted[ch.problem]["contested"] = True
                notes.append(f"{ch.problem}: refuted, but metrics confirm it -> kept as contested")
        elif ch.verdict == "weaker":
            accepted[ch.problem]["contested"] = True
        out.append(ch)
    return out, accepted, notes


# ---------- 3 Strategist (remote) ----------
def strategy_message(client, G, roots, variants, gates, leadership, cases) -> str:
    rc = "\n".join(f"- {r.problem} ({r.label}): {r.role}, priority {r.weight:.2f}; causes {', '.join(r.causes) or '-'}; "
                   f"caused by {', '.join(r.caused_by) or '-'}" for r in roots.causes)
    drafts = []
    for v in variants:
        acts = "\n".join(f"    - {i['action']} ({label(G, i['action'])}) fixes {', '.join(i['fixes'])}; evidence "
                         f"{', '.join(i['evidence']) or '-'}" for i in v["items"])
        drafts.append(f"* {v['plan_id']} variant={v['variant']}: {v['emphasis']}\n{acts}")
    allowed = "\n".join(f"- {a} ({label(G, a)}): fixes {', '.join(CATALOG[a]['fixes_concepts'])}"
                        + ("" if g.earliest_phase == 1 else f"; not before phase {g.earliest_phase}: {g.reason}")
                        for a, g in gates.items() if g.allowed)
    blocked = "\n".join(f"- {a}: {g.reason}" for a, g in gates.items() if not g.allowed) or "- none"
    req = "\n".join(f"- {d.intervention_id}: RULE VERDICT = {d.decision}" + (f" to phase {d.to_phase}" if d.to_phase else "")
                    + f" ({d.reason})" for d in leadership) or "- none"
    prec = "\n".join(f"- {c.case} {c.name}: {c.outcome}" for c in cases if c.worker_fit and c.score > 0) or "- none"
    docs = documents()
    research = "\n".join(f"- {d}: {docs[d]['text']}" for d in sorted(docs) if d.startswith(("R", "FN"))
                         and (not d.startswith("R") or check_relevance(G, d, client).relevant))
    segs = "\n".join(f"- {s.name.replace('_', ' ')} ({s.flag})" for s in client.segments) or "- none"
    return (_header(client) + f"\nROOT CAUSES AND SYMPTOMS:\n{rc}\n\nDRAFT PLANS:\n" + "\n".join(drafts)
            + f"\n\nALLOWED ACTIONS:\n{allowed}\n\nBLOCKED ACTIONS (never use):\n{blocked}\n\nLEADERSHIP REQUESTS:\n{req}"
            + f"\n\nSITES / SEGMENTS:\n{segs}\nCOHORTS: {client.internal.get('cohort_and_site_asymmetries', 'n/a')}"
            + f"\n\nPRECEDENT CASES:\n{prec}\n\nRESEARCH AND FIELD NOTES:\n{research}")


async def strategize(message: str, trace_calls, issues: list[CriticIssue] | None = None, previous=None):
    if issues is None:
        obj, info = await call("strategist", "remote", P.STRATEGIST, message, StrategyDrafts)
    else:
        crit = "\n".join(f"- [{i.severity}] {i.plan_id} / {i.target or '-'}: {i.kind}: {i.detail}"
                         + (f" -> fix: {i.fix}" if i.fix else "") for i in issues)
        user = (message + "\n\nYOUR PREVIOUS PLANS:\n" + previous.model_dump_json(indent=1)
                + f"\n\nCRITIC ISSUES TO FIX:\n{crit}")
        obj, info = await call("strategist:revise", "remote", P.STRATEGIST_REVISE, user, StrategyDrafts)
    trace_calls.append(info)
    return obj


# ---------- 4 Plan critic: rules (deterministic) + LLM review ----------
def rule_check(G, client, drafts: StrategyDrafts, variants: list[dict], gates, targets: dict, leadership) -> list[CriticIssue]:
    """Deterministic checks. Same plans in -> same issues out."""
    issues = []
    vmap = {v["plan_id"]: v for v in variants}
    known_docs = set(documents())
    seen = set()
    for d in drafts.plans:
        if d.plan_id not in vmap or d.plan_id in seen:
            issues.append(CriticIssue(plan_id=d.plan_id, kind="rule_violation", severity="blocking", by="rules",
                                      detail="unknown or duplicate plan_id", fix=f"use one of {', '.join(vmap)}"))
            continue
        seen.add(d.plan_id)
        v = vmap[d.plan_id]
        chosen = []
        for ch in d.choices:
            if ch.action not in CATALOG:
                issues.append(CriticIssue(plan_id=d.plan_id, target=ch.action, kind="rule_violation", severity="blocking",
                                          by="rules", detail="not a catalog action id", fix="use an allowed action id or an original idea"))
            elif not gates[ch.action].allowed:
                issues.append(CriticIssue(plan_id=d.plan_id, target=ch.action, kind="rule_violation", severity="blocking",
                                          by="rules", detail=f"blocked for this client: {gates[ch.action].reason}", fix="remove it"))
            else:
                chosen.append(ch.action)
                _, ok = verify_scope(ch.scope, client)
                if not ok:
                    issues.append(CriticIssue(plan_id=d.plan_id, target=ch.action, kind="scope_problem", severity="minor",
                                              by="rules", detail=f"scope '{ch.scope}' is not in the client data", fix="use company-wide or a named site"))
                if strip_numbers(ch.why)[1]:
                    issues.append(CriticIssue(plan_id=d.plan_id, target=ch.action, kind="unsupported_claim", severity="minor",
                                              by="rules", detail="contains a number written by the model", fix="remove numbers"))
        dropped = {x.action for x in d.dropped if x.justification.strip()}
        for it in v["items"]:
            if it["action"] not in chosen and it["action"] not in dropped:
                issues.append(CriticIssue(plan_id=d.plan_id, target=it["action"], kind="unjustified_drop", severity="blocking",
                                          by="rules", detail="draft action removed without a justification",
                                          fix="keep it, or list it in 'dropped' with a data-based reason"))
        covered = {p for a in chosen for p in CATALOG[a]["fixes_concepts"]}
        covered |= {p for o in d.original_ideas for p in o.fixes}
        for p in v["targets"]:
            if p not in covered:
                issues.append(CriticIssue(plan_id=d.plan_id, target=p, kind="missing_coverage", severity="blocking", by="rules",
                                          detail=f"no action addresses {label(G, p)}", fix="add an allowed action that fixes it"))
        for o in d.original_ideas:
            bad_p = [p for p in o.fixes if p not in targets]
            bad_e = [e for e in o.evidence if e not in known_docs or (G.nodes[e]["kind"] in ("case", "snippet")
                                                                      and not check_relevance(G, e, client).relevant)]
            if not o.fixes or bad_p or not o.evidence or len(bad_e) == len(o.evidence):
                issues.append(CriticIssue(plan_id=d.plan_id, target=o.title, kind="original_unsupported", severity="blocking",
                                          by="rules", detail="original idea without a valid problem id or relevant evidence "
                                          f"(problems {bad_p or '-'}, evidence {bad_e or '-'})", fix="cite a root-cause id and a relevant C/R/FN id"))
            if strip_numbers(o.description)[1]:
                issues.append(CriticIssue(plan_id=d.plan_id, target=o.title, kind="unsupported_claim", severity="minor",
                                          by="rules", detail="contains a number written by the model", fix="remove numbers"))
        if strip_numbers(d.thesis)[1]:
            issues.append(CriticIssue(plan_id=d.plan_id, target="thesis", kind="unsupported_claim", severity="minor",
                                      by="rules", detail="thesis contains a number written by the model", fix="remove numbers"))
        verdict_of = {x.intervention_id: x.decision for x in leadership}
        for rv in d.request_views:
            dec = verdict_of.get(rv.request)
            t = rv.explanation.lower()
            if dec is None:
                continue
            if (dec == "blocked" and re.search(r"\b(adopt|approve|implement now)\b", t)) or \
               (dec == "kept" and re.search(r"\b(reject|block)\b", t)):
                issues.append(CriticIssue(plan_id=d.plan_id, target=rv.request, kind="contradiction", severity="blocking",
                                          by="rules", detail=f"explanation contradicts the rule verdict '{dec}'", fix="explain the given verdict"))
    for pid in vmap:
        if pid not in seen:
            issues.append(CriticIssue(plan_id=pid, kind="rule_violation", severity="blocking", by="rules",
                                      detail="plan missing from the answer", fix="return all three plans"))
    return issues


async def llm_critic(message: str, drafts: StrategyDrafts, rule_issues, trace_calls) -> list[CriticIssue]:
    rules_txt = "\n".join(f"- {i.plan_id} / {i.target}: {i.kind}: {i.detail}" for i in rule_issues) or "- none"
    user = message + "\n\nREFINED PLANS:\n" + drafts.model_dump_json(indent=1) + f"\n\nRULE FINDINGS (already known):\n{rules_txt}"
    obj, info = await call("critic", "local", P.CRITIC, user, CriticReview)
    trace_calls.append(info)
    valid = []
    for d in drafts.plans:
        targets = {"thesis", ""} | {c.action for c in d.choices} | {o.title for o in d.original_ideas}
        for i in obj.issues:
            if i.plan_id == d.plan_id and i.target in targets and i.detail.strip():
                i.by = "llm"
                if i.kind in RULE_OWNED:          # phases, gates, coverage and drops are decided by the rule checks only
                    i.severity = "minor"
                    i.detail = "(advisory, rules own this check) " + i.detail
                valid.append(i)
    return valid


RULE_OWNED = {"rule_violation", "missing_coverage", "unjustified_drop"}


# ---------- 5 Jury (mixed models, rubric, rotated order) ----------
async def jury(client, G, plans, roots, trace_calls, priorities_txt: str = "") -> list[JurorBallot]:
    def block(p):
        acts = "\n".join(f"    phase {a.phase}: {a.action if not a.original else 'original'} - {a.label} ({a.scope})"
                         for a in p.actions)
        return (f"* plan_id={p.plan_id}: {p.title}\n  thesis: {p.thesis}\n  estimated cost: EUR {p.cost_eur:,.0f}\n"
                f"  root causes covered: {p.coverage * 100:.0f}%\n  actions:\n{acts}")
    rc = "\n".join(f"- {r.problem}: {r.label} ({r.role})" for r in roots.causes if r.role != "symptom")

    async def one(i, persona):
        order = plans[i % len(plans):] + plans[:i % len(plans)]           # deterministic rotation against position bias
        user = _header(client) + f"\nROOT CAUSES:\n{rc}\n\nPLANS:\n" + "\n\n".join(block(p) for p in order) + priorities_txt
        sys = P.JUROR.format(persona=persona, description=PERSONA_DESCRIPTIONS[persona])
        try:
            obj, info = await call(f"juror:{persona}", JUROR_TIER[persona], sys, user, JurorBallot)
            trace_calls.append(info)
            obj.persona = persona
            return obj, [p.plan_id for p in order]
        except Exception as e:  # a failed juror is reported by the jury critic, not fatal
            trace_calls.append({"model": "failed", "cached": False, "attempts": 0, "error": str(e)[:200]})
            return None, None
    res = await asyncio.gather(*(one(i, p) for i, p in enumerate(JURY_PERSONAS)))
    ballots = []
    for b, order in res:
        if b is not None:
            b.scores = [s for s in b.scores if s.plan_id in {p.plan_id for p in plans}]
            ballots.append((b, order))
    return ballots


def jury_critic(G, plans, ballots_with_order, det_scores: dict, margin_rule: float = 0.03) -> JuryAudit:
    """Deterministic audit of the jury: unsupported votes, inconsistent verdicts, outliers, position bias.
    Returns per-vote weights and the validated jury score per plan."""
    flags, weights = [], {}
    plan_ids = [p.plan_id for p in plans]
    plan_refs = {p.plan_id: {a.action for a in p.actions} | {e for a in p.actions for e in a.evidence + a.precedents}
                 for p in plans}
    comp = {}
    for b, order in ballots_with_order:
        for s in b.scores:
            comp[(b.persona, s.plan_id)] = (s.feasibility + s.impact + s.evidence + (6 - s.risk)) / 4
    for b, order in ballots_with_order:
        for s in b.scores:
            k, w = f"{b.persona}|{s.plan_id}", 1.0
            if not set(s.cites) & plan_refs[s.plan_id]:
                w *= 0.5
                flags.append(f"{b.persona} on {s.plan_id}: cites nothing that is in the plan -> half weight")
            c = comp[(b.persona, s.plan_id)]
            if (s.verdict == "reject" and c >= 4) or (s.verdict == "approve" and c <= 2):
                w *= 0.5
                flags.append(f"{b.persona} on {s.plan_id}: verdict '{s.verdict}' contradicts its own scores -> half weight")
            others = [v for (per, pid), v in comp.items() if pid == s.plan_id and per != b.persona]
            if len(others) >= 2 and abs(c - median(others)) > 1.5:
                w *= 0.75
                flags.append(f"{b.persona} on {s.plan_id}: outlier vs the other jurors -> reduced weight")
            weights[k] = round(w, 3)
    firsts = [max(b.scores, key=lambda s: comp[(b.persona, s.plan_id)]).plan_id == order[0]
              for b, order in ballots_with_order if b.scores]
    if len(firsts) >= 3 and all(firsts):
        flags.append("every juror preferred the plan shown first: possible position bias, jury weight halved")
    missing = len(JURY_PERSONAS) - len(ballots_with_order)
    if missing:
        flags.append(f"{missing} juror(s) failed to answer")
    scores = {}
    for pid in plan_ids:
        num = sum(comp[(b.persona, pid)] * weights.get(f"{b.persona}|{pid}", 0) for b, _ in ballots_with_order
                  if (b.persona, pid) in comp)
        den = sum(weights.get(f"{b.persona}|{pid}", 0) for b, _ in ballots_with_order if (b.persona, pid) in comp)
        scores[pid] = round((num / den - 1) / 4, 4) if den else 0.0          # composite 1..5 -> 0..1
    bias = len(firsts) >= 3 and all(firsts)
    finals = {pid: (0.5 * (scores[pid] * (0.5 if bias else 1.0)) + 0.5 * det_scores[pid]) for pid in plan_ids}
    ranked = sorted(plan_ids, key=lambda p: -finals[p])
    margin = finals[ranked[0]] - finals[ranked[1]] if len(ranked) > 1 else 1.0
    decided = "jury"
    if margin < margin_rule:
        decided = "deterministic_tiebreak"
        flags.append(f"top plans within {margin_rule}: winner decided by the deterministic score for stability")
    return JuryAudit(weights=weights, flags=flags, plan_scores=scores, margin=round(margin, 4), decided_by=decided)
