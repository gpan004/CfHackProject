"""Track A parsing and Track B cleaning / normalization (§6.1–6.4)."""
import copy
import json
import re
from functools import lru_cache

from .config import (SANDBOX_FILE, SNAPSHOT_FILE, STATUS_TOL, SEGMENT_WEAK_DELTA, SEGMENT_STRONG_REL, PILLAR_IDS)
from .knowledge import (K, CATALOG, LOWER_IS_BETTER, NEUTRAL, ALIASES, tag_archetypes, tag_concepts,
                        tag_interventions, allowed, build_graph)
from .guardrails import readiness
from .schemas import (CaseStudy, InterventionStep, Snippet, FieldNote, MetricRow, Segment, NoiseFlag, ClientProfile)

SNAPSHOT_SECTIONS = ("public_reputation", "career_portal_and_funnel", "social_and_employee_voice", "hiring_and_retention_kpis")
PEER_SECTIONS = ("portal_funnel.", "social_and_advocacy.", "hiring_and_retention.")


# ---------- generic helpers ----------
def flatten(d: dict, prefix: str = "") -> dict[str, float]:
    out = {}
    for k, v in d.items():
        if k == "segment_or_site_breakdown":
            continue
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flatten(v, key))
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            out[key] = float(v)
    return out


def comparable(snapshot_t: dict) -> dict[str, tuple[float, str]]:
    out = {}
    for section in SNAPSHOT_SECTIONS:
        for k, v in flatten(snapshot_t.get(section, {}) or {}).items():
            out[ALIASES.get(k, k)] = (v, section)
    return out


def comparable_peer(peer: dict) -> dict[str, float]:
    out = {}
    for k, v in flatten(peer or {}).items():
        for p in PEER_SECTIONS:
            if k.startswith(p):
                k = k[len(p):]
        out[ALIASES.get(k, k)] = v
    return out


def status(key: str, value: float, peer: float | None) -> str:
    leaf = key.split(".")[-1]
    if peer is None or leaf in NEUTRAL:
        return "no_benchmark"
    rel = 0.0 if value == peer else ((value - peer) / abs(peer) if peer != 0 else (1.0 if value > peer else -1.0))
    if leaf in LOWER_IS_BETTER:
        rel = -rel
    return "better" if rel > STATUS_TOL else "worse" if rel < -STATUS_TOL else "in_line"


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def split_sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]


# ---------- raw data ----------
@lru_cache
def sandbox() -> dict:
    return json.loads(SANDBOX_FILE.read_text(encoding="utf-8"))


@lru_cache
def snapshots() -> dict:
    return json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))


def pillars() -> list[dict]:
    return [{"id": pid, **p} for pid, p in zip(PILLAR_IDS, sandbox()["domain_pillars_and_causal_dynamics"]["pillars"])]


def scenarios() -> list[dict]:
    return sandbox()["company_scenarios_to_diagnose"]


def scenario_snapshot(code: str) -> dict | None:
    return next((s for s in snapshots()["active_scenario_analytics_snapshots"] if s["scenario_code"] == code), None)


# ---------- Track A ----------
def build_field_notes() -> list[FieldNote]:
    out = []
    for raw in sandbox()["domain_pillars_and_causal_dynamics"]["raw_cross_pillar_rules_to_structure"]:
        m = re.match(r"\s*Field Note\s+(\d+)\s*\(([^)]*)\)\s*:\s*(.*)", raw, re.S)
        if m:
            out.append(FieldNote(id=f"FN{m.group(1)}", title=m.group(2), text=m.group(3), concepts=tag_concepts(m.group(3))))
    return out


def build_snippets() -> list[Snippet]:
    return [Snippet(id=f"R{s['snippet_no']}", source=s["source"], finding=s["finding"],
                    concepts=tag_concepts(s["finding"]), archetypes=tag_archetypes(s["finding"]))
            for s in sandbox()["raw_empirical_research_snippets"]]


def build_cases() -> list[CaseStudy]:
    snaps = {s["case_name"]: s for s in snapshots()["case_study_analytics_snapshots"]}
    out = []
    for n, c in enumerate(sandbox()["raw_case_study_narratives"], 1):
        prof = c["sector_and_profile"]
        arch_text = prof.split("Target talent:", 1)[1] if "Target talent:" in prof else prof
        parts = re.split(r"\s*(\d+)\.\s+", c["intervention_sequence"])
        steps = [InterventionStep(step=int(parts[i]), text=parts[i + 1].strip(), intervention_ids=tag_interventions(parts[i + 1]))
                 for i in range(1, len(parts) - 1, 2)]
        if not steps:
            steps = [InterventionStep(step=1, text=c["intervention_sequence"], intervention_ids=tag_interventions(c["intervention_sequence"]))]
        ids = list(dict.fromkeys(i for s in steps for i in s.intervention_ids))
        concepts = tag_concepts(c["initial_challenge"]) + [x for i in ids for x in CATALOG[i]["fixes_concepts"]]
        snap = snaps.get(c["case_name"], {})
        t0 = {k: v for k, (v, _) in comparable(snap.get("t0_before_intervention", {})).items()}
        t1 = {k: v for k, (v, _) in comparable(snap.get("t1_after_12_months", {})).items()}
        deltas = {k: (t1[k] - t0[k]) / t0[k] for k in t0 if k in t1 and t0[k] != 0}
        out.append(CaseStudy(id=f"C{n:02d}", name=c["case_name"], sector_profile=prof, archetypes=tag_archetypes(arch_text),
                             problem=c["initial_challenge"], problem_concepts=list(dict.fromkeys(concepts)),
                             interventions=steps, intervention_ids=ids, measured_roi_text=c["measured_roi"],
                             kpis_t0=t0, kpis_t1=t1, kpi_deltas=deltas))
    return out


@lru_cache
def track_a() -> dict:
    cases, snippets, fns = build_cases(), build_snippets(), build_field_notes()
    return {"cases": cases, "snippets": snippets, "field_notes": fns, "graph": build_graph(cases, snippets, fns)}


# ---------- Track B ----------
def _noise_reason(sentence: str, arch: list[str]) -> str | None:
    low = sentence.lower()
    for m in K["noise_markers"]:
        if m in low:
            return f"contains the noise marker '{m}'"
    for i in K["interventions"]:
        for s in i["synonyms"]:
            if s in low and not allowed(i["allowed_archetypes"], arch):
                return f"mentions '{s}', allowed only for {', '.join(i['allowed_archetypes'])}; client is {', '.join(arch) or 'unknown'} (FN6)"
    for c in K["concepts"]:
        for s in c["synonyms"]:
            if s in low and not allowed(c["archetype_scope"], arch):
                return f"mentions '{s}', relevant only for {', '.join(c['archetype_scope'])}; client is {', '.join(arch) or 'unknown'} (FN6)"
    return None


def _agency_spend(text: str) -> float | None:
    for sent in split_sentences(text):
        if "agenc" not in sent.lower():
            continue
        m = re.search(r"€\s?([\d.,]+)\s?([kKmM])?\s*/\s*(quarter|month|year)", sent)
        if m:
            num = m.group(1).rstrip(".,")
            num = num.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", num) else num.replace(",", ".")
            v = float(num) * {"k": 1e3, "m": 1e6}.get((m.group(2) or "").lower(), 1)
            return v * {"quarter": 4, "month": 12, "year": 1}[m.group(3)]
    return None


def build_client(scenario: dict, snapshot: dict | None, overrides: dict | None = None) -> ClientProfile:
    overrides = overrides or {}
    scenario = deep_merge(scenario, overrides.get("scenario", {}))
    snapshot = deep_merge(snapshot or {}, overrides.get("snapshot", {}))

    m = re.search(r"Declared EVP:\s*'([^']+)'", scenario.get("organizational_context", ""))
    arch = tag_archetypes(scenario.get("workforce_target", "")) or tag_archetypes(scenario.get("industry", ""))

    t0 = snapshot.get("t0_current_snapshot", {}) or {}
    peers = comparable_peer(snapshot.get("sector_peer_benchmarks", {}))
    metrics = {k: MetricRow(key=k, value=v, peer=peers.get(k), status=status(k, v, peers.get(k)), section=sec)
               for k, (v, sec) in comparable(t0).items()}

    peer_overall = peers.get("overall_review_rating_5")
    seg_raw = (t0.get("public_reputation", {}) or {}).get("segment_or_site_breakdown", {}) or {}
    best = max((s["rating_5"] for s in seg_raw.values()), default=0)
    segments = []
    for name, s in seg_raw.items():
        r = s["rating_5"]
        flag = ("weak" if r <= best - SEGMENT_WEAK_DELTA else
                "strong" if peer_overall is not None and r >= peer_overall * (1 + SEGMENT_STRONG_REL) else "normal")
        segments.append(Segment(name=name, reviews=int(s.get("reviews", 0)), rating=r, flag=flag))

    signals, noise = {}, []
    for key, text in (scenario.get("ingaze_platform_signals") or {}).items():
        keep = []
        for sent in split_sentences(text):
            reason = _noise_reason(sent, arch)
            if reason:
                noise.append(NoiseFlag(field=f"signals.{key}", sentence=sent, reason=reason))
            else:
                keep.append(sent)
        signals[key] = " ".join(keep)

    internal = {k: str(v) for k, v in (scenario.get("client_internal_context") or {}).items()}
    healthy = [f"{r.key}: {r.value:g} vs peer {r.peer:g} (better)" for r in metrics.values() if r.status == "better"]
    healthy += [f"Segment {s.name}: {s.rating} stars (strong)" for s in segments if s.flag == "strong"]
    if internal.get("healthy_metrics_and_strengths_not_to_break"):
        healthy.append(internal["healthy_metrics_and_strengths_not_to_break"])

    return ClientProfile(
        scenario_code=scenario.get("scenario_code", "UNSEEN"), company_name=scenario.get("company_name", "Unknown"),
        industry=scenario.get("industry", ""), workforce_target=scenario.get("workforce_target", ""),
        headcount=snapshot.get("headcount"), locations_count=snapshot.get("locations_count"),
        declared_evp=m.group(1) if m else None, archetypes=arch, signals=signals, internal=internal,
        narrative=scenario.get("narrative_situation_to_solve", ""), metrics=metrics, segments=segments, noise=noise,
        readiness=readiness(metrics), healthy_baselines=healthy,
        annual_agency_spend_eur=_agency_spend(internal.get("budget_and_capacity_constraints", "")),
        leadership_requests=tag_interventions(internal.get("leadership_perceptions_and_requests", "")))


def client_for(code: str | None = None, scenario: dict | None = None, snapshot: dict | None = None,
               overrides: dict | None = None) -> ClientProfile:
    if scenario is None:
        scenario = next(s for s in scenarios() if s["scenario_code"] == code)
        snapshot = snapshot or scenario_snapshot(code)
    elif snapshot is None and scenario.get("scenario_code"):
        try:
            snapshot = scenario_snapshot(scenario["scenario_code"])
        except FileNotFoundError:
            snapshot = None
    return build_client(scenario, snapshot, overrides)
