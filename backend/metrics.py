from statistics import mean

from .config import (W_PRE, W_FINAL, PENALTY_PER_FIX, PENALTY_CAP, KPI_PROJECTION_KEYS)
from .knowledge import K, ASSUMPTIONS
from .schemas import ScoredPlan, RoiLine, RoiResult, KpiProjection

FIX_DECISIONS = ("moved", "blocked", "deferred_beyond_plan", "added")


def pre_score(plan, kept, decisions, root_ids: set[str], case_score_norm: dict) -> ScoredPlan:
    covered = {x for act in kept for x in act.addresses if x in root_ids}
    coverage = len(covered) / max(1, len(root_ids))
    cited = [case_score_norm[c] for act in kept for c in act.evidence if c in case_score_norm]
    evidence = sum(cited) / len(cited) if cited else 0.0
    fixes = sum(d.decision in FIX_DECISIONS for d in decisions)
    penalty = min(PENALTY_CAP, PENALTY_PER_FIX * fixes)
    plan = plan.model_copy(update={"actions": kept})
    return ScoredPlan(plan=plan, decisions=decisions, coverage=coverage, evidence=evidence, penalty=penalty,
                      pre_score=W_PRE["coverage"] * coverage + W_PRE["evidence"] * evidence - penalty)


def apply_jury(sp: ScoredPlan, verdicts) -> ScoredPlan:
    votes = [(v.persona, vote) for v in verdicts for vote in v.votes if vote.plan_id == sp.plan.plan_id]
    scores = [(vote.feasibility + vote.impact + (11 - vote.risk)) / 3 for _, vote in votes]
    jury = mean(scores) / 10 if scores else 0.0
    final = W_FINAL["jury"] * jury + W_FINAL["coverage"] * sp.coverage + W_FINAL["evidence"] * sp.evidence - sp.penalty
    return sp.model_copy(update={"jury": jury, "final": final, "votes": votes})


def rank(plans: list[ScoredPlan]) -> list[ScoredPlan]:
    return sorted(plans, key=lambda p: (-(p.final or 0), sum(d.decision in FIX_DECISIONS for d in p.decisions), p.plan.plan_id))


def _mv(client, key):
    r = client.metrics.get(key)
    return r.value if r else None


def benefit_line(name, spec, plan_ids, top_cases, client) -> RoiLine:
    applies = bool(set(plan_ids) & set(spec["interventions"]))
    cases = [c for c in top_cases if set(c.intervention_ids) & set(spec["interventions"])] or top_cases
    changes = [c.kpi_deltas[spec["metric"]] for c in cases if spec["metric"] in c.kpi_deltas]
    ids = [c.id for c in cases if spec["metric"] in c.kpi_deltas]
    empty = dict(name=name, base_value=None, expected_change=None, conservative_change=None,
                 benefit_expected_eur=0.0, benefit_conservative_eur=0.0, precedent_case_ids=ids)
    if not applies:
        return RoiLine(applies=False, formula="no plan intervention drives this line", **empty)
    if not changes:
        return RoiLine(applies=False, formula=f"no precedent telemetry for {spec['metric']}", **empty)
    expected = mean(changes)
    increase = name == "emv"
    conservative = min(changes) if increase else max(changes)
    hr, cpm = ASSUMPTIONS["hourly_hr_cost_eur"], ASSUMPTIONS["emv_cpm_eur"]
    base, formula = {
        "attrition_exposure": (_mv(client, "estimated_annual_attrition_exposure_eur"),
                               "annual attrition exposure € × −Δ attrition exposure in precedents"),
        "agency_spend": (client.annual_agency_spend_eur, "annual agency spend € × −Δ agency-filled roles % in precedents"),
        "hr_hours": ((_mv(client, "manual_hr_tracking_hours_month") or 0) * 12 * hr or None,
                     f"manual HR hours/month × 12 × €{hr}/h × −Δ manual hours in precedents"),
        "emv": ((_mv(client, "quarterly_organic_impressions") or 0) * 4 / 1000 * cpm or None,
                f"quarterly organic impressions × 4 / 1000 × €{cpm} CPM × Δ impressions in precedents"),
    }[name]
    if base is None:
        return RoiLine(applies=False, formula="no base value in client intake", **empty)
    sign = 1 if increase else -1
    return RoiLine(name=name, applies=True, base_value=base, expected_change=expected, conservative_change=conservative,
                   benefit_expected_eur=max(0.0, base * sign * expected),
                   benefit_conservative_eur=max(0.0, base * sign * conservative),
                   precedent_case_ids=ids, formula=formula)


def roi(plan_actions, top_cases, client) -> RoiResult:
    plan_ids = [a.intervention_id for a in plan_actions]
    lines = [benefit_line(n, spec, plan_ids, top_cases, client) for n, spec in K["benefit_lines"].items()]
    uc = ASSUMPTIONS["unit_cost_eur"]
    cost = (sum(uc[i] for i in set(plan_ids) if i in uc)
            + ASSUMPTIONS["original_action_cost_eur"] * sum(i == "original" for i in plan_ids))
    be = sum(l.benefit_expected_eur for l in lines)
    bc = sum(l.benefit_conservative_eur for l in lines)
    return RoiResult(lines=lines, cost_eur=cost, benefit_expected_eur=be, benefit_conservative_eur=bc,
                     roi_expected=(be - cost) / cost if cost > 0 else None,
                     roi_conservative=(bc - cost) / cost if cost > 0 else None,
                     payback_months_expected=cost / (be / 12) if be > 0 else None)


def kpi_projection(client, top_cases) -> list[KpiProjection]:
    out = []
    for k in KPI_PROJECTION_KEYS:
        row = client.metrics.get(k)
        if row is None:
            continue
        ch = [c.kpi_deltas[k] for c in top_cases if k in c.kpi_deltas]
        change = mean(ch) if ch else None
        out.append(KpiProjection(key=k, t0=row.value, peer=row.peer, change=change,
                                 projected=row.value * (1 + change) if change is not None else None))
    return out
