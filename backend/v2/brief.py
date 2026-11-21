"""The readable layer: confidence, 'answer in one minute' cards, a deterministic template brief, and the LLM report
writer whose every sentence is verified (no digits outside {{tokens}}, only known [IDs]); invalid sentences are dropped
and an empty section falls back to the template."""
import re

from .kg import documents, facts, in_edges, out_edges, label
from .llm import call
from . import prompts as P
from .schemas import Confidence, ReportDraft, ReportSection, Brief
from .tools import check_relevance

HEADINGS = ["What is going on", "Why it is happening", "What to do, in what order", "What we will not do, and why",
            "What it costs and returns", "How sure we are"]
TOKEN_RE = re.compile(r"\{\{\s*([a-z_]+)(?::([A-Za-z0-9_.]+))?\s*\}\}")
CITE_RE = re.compile(r"\[([A-Z]{1,2}\d{1,2})\]")
PHASE_WORD = {1: "first", 2: "second", 3: "third"}


def eur(v) -> str:
    return "€" + f"{v:,.0f}"


def fmt_metric(G, key, v) -> str:
    unit = G.nodes[key].get("unit", "") if key in G else ""
    if v is None:
        return "n/a"
    if unit.startswith("%"):
        return f"{v:g}%"
    if unit.startswith("stars"):
        return f"{v:g} stars"
    if unit == "EUR":
        return eur(v)
    return f"{v:g} {unit.split(' (')[0]}".strip()


# ---------- confidence ----------
def confidence(G, client, signals, accepted: dict) -> list[Confidence]:
    by, out = {s.problem: s for s in signals}, []
    for pid in sorted(accepted):
        s = by[pid]
        lit = sorted({u for u, _ in in_edges(G, pid, "mentions")
                      if G.nodes[u]["kind"] == "field_note" or check_relevance(G, u, client).relevant})
        prec = sorted(c for c, _ in in_edges(G, pid, "had_problem") if check_relevance(G, c, client).relevant)
        m, t, contested = len(s.measured), len(s.text), accepted[pid]["contested"]
        if m and len(lit) + len(prec) >= 2 and not contested:
            lvl, why = "high", "measured against peers and backed by research or precedent cases"
        elif m or (t and lit):
            lvl = "medium"
            why = ("measured, but challenged by the critic agents" if contested and m
                   else "measured against peers, little outside evidence" if m else "stated by the client and backed by research")
        else:
            lvl, why = "low", "only mentioned in the client's text"
        out.append(Confidence(problem=pid, level=lvl, metric_evidence=m, text_evidence=t, literature=len(lit),
                              precedents=len(prec), reason=why))
    return out


# ---------- facts used by both the template and the writer ----------
def _top_metric(G, s):
    ms = sorted(s.measured, key=lambda m: -(m.gap_pct or 0))
    return ms[0] if ms else None


def tokens_for(client, roi) -> dict[str, str]:
    t = {"cost": eur(roi.cost_eur), "benefit": eur(roi.benefit_expected_eur) + " per year",
         "benefit_conservative": eur(roi.benefit_conservative_eur) + " per year",
         "payback": "n/a" if roi.payback_months_expected is None else f"{roi.payback_months_expected:.1f} months",
         "roi": "n/a" if roi.roi_expected is None else f"{roi.roi_expected * 100:+.0f}%"}
    return t


def render(text: str, G, client, toks: dict) -> tuple[str, bool]:
    ok = True

    def rep(m):
        nonlocal ok
        name, arg = m.group(1), m.group(2)
        if name in toks and arg is None:
            return toks[name]
        if name == "compare" and arg in client.metrics:     # self-labelled, so a token used for the wrong metric is visible
            r = client.metrics[arg]
            peer = "" if r.peer is None else f" vs peers {fmt_metric(G, arg, r.peer)}"
            return f"{label(G, arg).lower()}: {fmt_metric(G, arg, r.value)}{peer}"
        ok = False
        return ""
    return TOKEN_RE.sub(rep, text), ok


STOP = {"rating", "share", "score", "rate", "with", "from", "that", "spent", "hours", "month", "between", "across",
        "employee", "employees", "the", "and"}


def metric_words(G, key) -> set[str]:
    """Words that must appear in a sentence that cites this metric: its label and the problems it indicates."""
    words = set(re.findall(r"[a-z]{4,}", label(G, key).lower()))
    for p, _ in in_edges(G, key, "indicated_by"):
        words |= set(re.findall(r"[a-z]{4,}", (label(G, p) + " " + p.replace("_", " ")).lower()))
    return words - STOP


NUM_RE = re.compile(r"(?<![A-Za-z0-9])€?\d[\d,.]*(?:\s?(?:months|stars|per year|%))?")   # numbers, but not ids like C05/FN4


def allowed_names(G) -> list[str]:
    """Proper names that legitimately contain digits (e.g. '360-Degree Internal Listening'), longest first."""
    names = {G.nodes[n].get("label", "") for n in G.nodes if G.nodes[n].get("kind") in ("action", "case", "problem", "metric")}
    return sorted((x for x in names if re.search(r"\d", x)), key=len, reverse=True)


def validate_sentence(s: str, G, client, toks) -> tuple[str | None, str]:
    if "<number>" in s:
        return None, "copied a hidden-number placeholder"
    bare = CITE_RE.sub("", TOKEN_RE.sub("", s))
    for name in allowed_names(G):
        bare = re.sub(re.escape(name), "", bare, flags=re.I)
    if re.search(r"\d", bare):
        return None, "contains a number not produced by Python"
    for cid in CITE_RE.findall(s):
        if cid not in documents():
            return None, f"cites unknown source [{cid}]"
    context = TOKEN_RE.sub(" ", s).lower()
    for name, arg in TOKEN_RE.findall(s):
        if name == "compare" and arg in client.metrics and not any(w in context for w in metric_words(G, arg)):
            return None, f"uses the number of '{label(G, arg)}' in a sentence about something else"
    out, ok = render(s, G, client, toks)
    return (out, "") if ok else (None, "uses an unknown {{token}}")


# ---------- deterministic template ----------
def template_sections(G, client, signals, accepted, roots, plan, leadership, roi, cases, conf, critic_rounds, audit,
                      stability_note) -> list[ReportSection]:
    by = {s.problem: s for s in signals}
    probs = sorted((by[p] for p in accepted), key=lambda s: -s.severity)
    s1 = [f"{client.company_name} shows {len(probs)} confirmed problems compared with its sector peers."]
    for s in probs[:3]:
        m = _top_metric(G, s)
        s1.append(f"{s.label}: {s.plain}" + (f" ({m.label}: {fmt_metric(G, m.key, m.value)} vs peers "
                                             f"{fmt_metric(G, m.key, m.peer)})." if m and m.peer is not None else ""))
    rootl = [r for r in roots.causes if r.role in ("root", "standalone")][:3]
    s2 = []
    for r in rootl:
        if r.causes:
            ev = sorted({e.ref for l in roots.links if l.source == r.problem for e in l.evidence if e.kind == "document"})
            s2.append(f"{r.label} drives {', '.join(label(G, c).lower() for c in r.causes)}"
                      + (f" [{'] ['.join(ev[:3])}]." if ev else "."))
        else:
            s2.append(f"{r.label} is a standalone problem: it needs its own fix.")
    sym = [r.label.lower() for r in roots.causes if r.role == "symptom"]
    if sym:
        s2.append(f"Symptoms such as {', '.join(sym[:4])} should improve once their causes are fixed, so we do not treat them directly.")
    s3 = []
    for ph in (1, 2, 3):
        acts = [a for a in plan.actions if a.phase == ph]
        if acts:
            s3.append(f"In the {PHASE_WORD[ph]} phase: " + "; ".join(a.label for a in acts) + ". "
                      + (acts[0].why_now if acts[0].why_now else ""))
    s4 = []
    for d in leadership:
        word = {"kept": "adopted", "moved": f"postponed to the {PHASE_WORD.get(d.to_phase, 'later')} phase",
                "blocked": "not adopted", "deferred_beyond_plan": "not adopted in this plan"}.get(d.decision, d.decision)
        s4.append(f"Leadership request '{label(G, d.intervention_id)}' is {word}: {d.reason}.")
    for h in client.healthy_baselines[:3]:
        s4.append(f"We protect what already works: {h}.")
    s5 = [f"The plan costs about {eur(roi.cost_eur)} and is expected to return {eur(roi.benefit_expected_eur)} per year "
          f"({eur(roi.benefit_conservative_eur)} in the conservative case)."]
    if roi.payback_months_expected:
        s5.append(f"Expected payback is {roi.payback_months_expected:.1f} months.")
    prec = [c for c in cases if c.worker_fit and c.score > 0][:3]
    if prec:
        s5.append("These figures come from the measured results of similar companies: "
                  + "; ".join(f"{c.name.split(' (')[0]} [{c.case}]" for c in prec) + ". No number is generated by AI.")
    hi = sum(c.level == "high" for c in conf)
    s6 = [f"{hi} of {len(conf)} problems have high confidence (measured against peers and backed by research or precedents).",
          f"The plan critic reviewed the strategy in {len(critic_rounds)} round(s); "
          f"{sum(len(r.issues) for r in critic_rounds)} issue(s) were raised and resolved or corrected automatically."]
    if audit:
        s6.append(f"The jury of five stakeholders was audited: {len(audit.flags)} flag(s); the winner was decided by "
                  + ("the jury." if audit.decided_by == "jury" else "the deterministic score because the jury was split."))
    if stability_note:
        s6.append(stability_note)
    cite = lambda t: re.sub(r"\((FN\d|R\d{1,2}|C\d{2})\)", r"[\1]", t)       # (FN5) -> [FN5] so the UI shows source chips
    return [ReportSection(heading=h, text=cite(" ".join(x for x in t if x))) for h, t in zip(HEADINGS, [s1, s2, s3, s4, s5, s6])]


def one_minute(G, client, signals, accepted, roots, plan, leadership, roi, cases) -> list[dict]:
    by = {s.problem: s for s in signals}
    tops = [r for r in roots.causes if r.role in ("root", "standalone")][:3]
    cards = []
    if tops:
        top = tops[0]
        s = by.get(top.problem)
        m = _top_metric(G, s) if s else None
        driven = sorted({label(G, c) for t in tops for c in t.causes})
        cards.append({"title": "The root causes", "text": "; ".join(t.label for t in tops) + ".",
                      "detail": (f"Strongest signal: {m.label} {fmt_metric(G, m.key, m.value)} vs peers "
                                 f"{fmt_metric(G, m.key, m.peer)}. " if m and m.peer is not None else "")
                      + (("Together they drive: " + ", ".join(driven).lower() + ".") if driven else "")})
    first = [a for a in plan.actions if a.phase == 1]
    if first:
        cards.append({"title": "The first move", "text": "; ".join(a.label for a in first) + ".",
                      "detail": "Measure before changing anything: diagnostics come first so every later step targets the right teams."})
    if roi.payback_months_expected:
        cards.append({"title": "The payoff", "text": f"{eur(roi.benefit_expected_eur)} per year for {eur(roi.cost_eur)}; "
                      f"payback in {roi.payback_months_expected:.1f} months.",
                      "detail": f"Conservative case: {eur(roi.benefit_conservative_eur)} per year. Based on measured results of similar companies."})
    else:
        cards.append({"title": "The payoff", "text": f"Estimated cost {eur(roi.cost_eur)}.",
                      "detail": "No precedent gives a measured money benefit for this plan; the value is in the problems it fixes."})
    no = [d for d in leadership if d.decision in ("blocked", "moved", "deferred_beyond_plan")]
    if no:
        d = no[0]
        cards.append({"title": "What we push back on", "text": f"{label(G, d.intervention_id)}: "
                      + ("not now" if d.decision == "moved" else "no") + ".", "detail": d.reason})
    return cards


def glossary(G, plan, roots) -> dict[str, str]:
    g = dict(facts()["glossary"]["terms"])
    for r in roots.causes:
        g[r.label] = r.plain
    for a in plan.actions:
        if a.plain:
            g[a.label] = a.plain
    return g


# ---------- report writer agent ----------
async def write_brief(G, client, signals, accepted, roots, plan, leadership, roi, cases, conf, critic_rounds, audit,
                      stability_note, trace_calls, notes) -> Brief:
    # the writer never sees run-specific text (stability note), so the same analysis always gets the same brief
    template = template_sections(G, client, signals, accepted, roots, plan, leadership, roi, cases, conf, critic_rounds,
                                 audit, "")
    toks = tokens_for(client, roi)
    metric_tokens = sorted({m.key for s in signals if s.problem in accepted for m in s.measured})
    allowed_tokens = ", ".join([f"{{{{{k}}}}}" for k in toks] + [f"{{{{compare:{k}}}}}" for k in metric_tokens])
    facts_txt = "\n\n".join(f"## {s.heading}\n{TOKEN_RE.sub('', s.text)}" for s in template)
    names = allowed_names(G)
    protected = {"@@" + "".join(chr(97 + int(d)) for d in str(i)) + "@@": n for i, n in enumerate(names)}  # no digits
    for k, n in protected.items():
        facts_txt = re.sub(re.escape(n), k, facts_txt, flags=re.I)
    facts_txt = NUM_RE.sub("<number>", facts_txt)
    for k, n in protected.items():
        facts_txt = facts_txt.replace(k, n)
    user = (f"VERIFIED FACTS (numbers are hidden: use the tokens):\n{facts_txt}\n\nAVAILABLE TOKENS: {allowed_tokens}\n"
            "A {{compare:KEY}} token renders as '<metric name>: <client value> vs peers <peer value>' with units, so do not "
            "repeat the name or the unit around it. Only use it in a sentence about that metric. KEY MEANS: "
            + "; ".join(f"{k} = {label(G, k)}" for k in metric_tokens))
    sys = P.REPORT_WRITER.format(headings=" | ".join(HEADINGS), tokens=allowed_tokens)
    dropped, sections, writer = [], [], "llm_verified"
    headline = f"{client.company_name}: fix {next((r.label.lower() for r in roots.causes if r.role in ('root', 'standalone')), 'the root causes')} first"
    try:
        draft, info = await call("report_writer", "remote", sys, user, ReportDraft)
        trace_calls.append(info)
        h, ok = validate_sentence(draft.headline, G, client, toks)
        headline = h or headline
        got = {s.heading.strip().lower(): s for s in draft.sections}
        for tmpl in template:
            s = got.get(tmpl.heading.lower())
            keep = []
            for sent in re.split(r"(?<=[.!?])\s+", s.text.strip()) if s else []:
                v, why = validate_sentence(sent, G, client, toks)
                if v:
                    keep.append(v)
                elif sent.strip():
                    dropped.append(f"[{tmpl.heading}] {sent} -> {why}")
            sections.append(ReportSection(heading=tmpl.heading, text=" ".join(keep)) if keep else tmpl)
            if not keep:
                notes.append(f"report section '{tmpl.heading}' fell back to the template")
    except Exception as e:  # noqa: BLE001 - the template is always available
        notes.append(f"report writer unavailable ({str(e)[:120]}) -> deterministic template")
        sections, writer = template, "template"
    # completeness: every action of the plan must be named in the 'what to do' section
    i = HEADINGS.index("What to do, in what order")
    dash = lambda t: re.sub(r"[‐-―]", "-", t.lower())
    missing = [a for a in plan.actions if dash(a.label) not in dash(sections[i].text)]
    if missing:
        sections[i] = template[i]
        notes.append(f"report omitted {', '.join(a.label for a in missing)} -> section replaced by the complete template")
    if all(s is t for s, t in zip(sections, template)):
        writer = "template"
    if stability_note:   # appended by Python after writing, so it never changes the writer's input
        last = sections[-1]
        sections[-1] = ReportSection(heading=last.heading, text=(last.text + " " + stability_note).strip())
    return Brief(headline=headline, one_minute=one_minute(G, client, signals, accepted, roots, plan, leadership, roi, cases),
                 sections=sections, writer=writer, dropped_sentences=dropped, glossary=glossary(G, plan, roots))
