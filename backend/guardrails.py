"""Readiness gate, sector fit, do-not-touch and phase placement (§6.6–6.8)."""
from .config import SAY_DO_GAP_STARS
from .knowledge import CATALOG, allowed, tag_interventions
from .schemas import Readiness, PlanAction, GuardrailDecision


def readiness(metrics: dict) -> Readiness:
    gap = metrics.get("external_claims_gap_stars_5")
    mgmt = metrics.get("sub_ratings_5.management")
    wlb = metrics.get("sub_ratings_5.work_life_balance")
    say_do = gap is not None and gap.value >= SAY_DO_GAP_STARS
    mgmt_bad = mgmt is not None and mgmt.status == "worse"
    wlb_bad = wlb is not None and wlb.status == "worse"
    unknown = gap is None and mgmt is None and wlb is None
    amb = metrics.get("active_organic_ambassadors_headcount")
    org = metrics.get("organic_employee_post_er_pct")
    organic = (amb is not None and amb.value > 0) or (org is not None and org.status in ("better", "in_line"))
    reasons = []
    if say_do:
        reasons.append(f"Say-do gap: claims gap {gap.value:g} ≥ {SAY_DO_GAP_STARS} stars (R1, FN4)")
    if mgmt_bad:
        reasons.append(f"Management friction: management {mgmt.value:g} vs peer {mgmt.peer:g}, worse (FN4, R5)")
    if wlb_bad:
        reasons.append(f"Burnout signal: work-life balance {wlb.value:g} vs peer {wlb.peer:g}, worse (FN4, R5)")
    if unknown:
        reasons.append("Unknown readiness: no claims-gap, management or work-life data; gate kept closed (FN4)")
    if organic:
        reasons.append("Organic advocacy present: "
                       + (f"{amb.value:g} active organic ambassadors" if amb is not None and amb.value > 0
                          else f"organic employee post ER {org.value:g} vs peer {org.peer}"))
    return Readiness(gate_open=not (say_do or mgmt_bad or wlb_bad or unknown), say_do_gap_active=say_do,
                     management_friction=mgmt_bad, burnout_signal=wlb_bad, organic_advocacy_present=organic,
                     unknown=unknown, reasons=reasons)


def sector_ok(item: dict, client_arch: list[str]) -> bool:  # FN6
    return allowed(item["allowed_archetypes"], client_arch)


def do_not_touch(item: dict, metrics: dict) -> bool:  # FN5
    rows = [metrics[k] for k in item["target_metrics"] if k in metrics and metrics[k].status != "no_benchmark"]
    return len(rows) > 0 and all(r.status == "better" for r in rows)


def blocked_reason(item: dict, client) -> tuple[str, str] | None:
    if not sector_ok(item, client.archetypes):
        return "sector_fit", (f"{item['name']} fits only {', '.join(item['allowed_archetypes'])}; "
                              f"client workforce is {', '.join(client.archetypes) or 'unknown'} (FN6)")
    if do_not_touch(item, client.metrics):
        ms = "; ".join(f"{k} {client.metrics[k].value:g} vs peer {client.metrics[k].peer:g}"
                       for k in item["target_metrics"] if k in client.metrics and client.metrics[k].status == "better")
        return "do_not_touch", f"{item['name']} targets metrics already better than peers: {ms} (FN5)"
    return None


def place(actions: list[PlanAction], client, sources: list[str] | None = None):
    """Returns (corrected kept actions, decisions). Python always wins over the LLM's phases."""
    r = client.readiness
    sources = sources or ["plan"] * len(actions)
    entries, decisions = [], []

    def decide(e, decision, rule, reason, to_phase=None):
        decisions.append(GuardrailDecision(subject=e["action"].action, intervention_id=e["action"].intervention_id,
                                           source=e["source"], decision=decision, from_phase=e["orig"],
                                           to_phase=to_phase, rule=rule, reason=reason))

    for a, src in zip(actions, sources):
        a = a.model_copy(deep=True)
        if a.intervention_id != "original" and a.intervention_id not in CATALOG:
            a.intervention_id = "original"
        cid = a.intervention_id if a.intervention_id != "original" else next(iter(tag_interventions(a.action)), None)
        e = {"action": a, "cid": cid, "source": src, "orig": a.phase, "status": "active", "rule": None, "reason": ""}
        entries.append(e)
        if cid is None:
            e["status"] = "original"
            continue
        b = blocked_reason(CATALOG[cid], client)
        if b:
            e["status"] = "blocked"
            decide(e, "blocked", b[0], b[1])

    # missing prerequisites (queue: added items are checked too)
    i = 0
    while i < len(entries):
        e = entries[i]; i += 1
        if e["status"] != "active":
            continue
        item = CATALOG[e["cid"]]
        present = {x["cid"] for x in entries if x["status"] == "active"}
        if item["prerequisites_any"] and not set(item["prerequisites_any"]) & present:
            cand = next((p for p in item["prerequisites_any"] if not blocked_reason(CATALOG[p], client)), None)
            if cand is None:
                e["status"] = "blocked"
                decide(e, "blocked", "prerequisite_unavailable",
                       f"none of the prerequisites ({', '.join(item['prerequisites_any'])}) can be run for this client")
                continue
            p = CATALOG[cand]
            new = PlanAction(action=p["name"], intervention_id=cand, phase=1, target_scope=e["action"].target_scope,
                             addresses=list(e["action"].addresses), evidence=[])
            entries.append({"action": new, "cid": cand, "source": "auto_added", "orig": None, "status": "active",
                            "rule": "prerequisite", "reason": f"added as prerequisite of {item['name']}", "added": True})

    # phase floors
    for _ in range(5):
        changed = False
        phase_of = {}
        for x in entries:
            if x["status"] == "active":
                phase_of[x["cid"]] = min(phase_of.get(x["cid"], 9), x["action"].phase)
        for e in entries:
            if e["status"] != "active":
                continue
            item = CATALOG[e["cid"]]
            present = [phase_of[p] for p in item["prerequisites_any"] if p in phase_of]
            floor, rule, reason = 1, None, ""
            if present:
                floor, rule = 1 + min(present), "prerequisite"
                reason = f"needs one of {', '.join(item['prerequisites_any'])} in an earlier phase (earliest: Phase {min(present)})"
            if item["requires_readiness"]:
                gate_floor = 3 if not r.gate_open else (1 if r.organic_advocacy_present else 2)
                if gate_floor >= floor and gate_floor > 1:
                    rule = "readiness_gate"
                    reason = ("readiness gate closed: " + "; ".join(x for x in r.reasons if not x.startswith("Organic"))
                              if not r.gate_open else "gate open but no organic advocacy base yet (FN4, R5)")
                floor = max(floor, gate_floor)
            if floor > 3:
                e["status"] = "deferred"; e["rule"], e["reason"] = rule, reason; changed = True
            elif e["action"].phase < floor:
                e["action"].phase = floor; e["rule"], e["reason"] = rule, reason; changed = True
        if not changed:
            break

    kept = []
    for e in entries:
        a = e["action"]
        if e["status"] == "original":
            decide(e, "kept", "original_unvalidated", "original action, no catalog item matched", a.phase)
            kept.append(a)
        elif e["status"] == "deferred":
            decide(e, "deferred_beyond_plan", e["rule"] or "prerequisite", e["reason"])
        elif e["status"] == "active":
            kept.append(a)
            if e.get("added"):
                decide(e, "added", "prerequisite", e["reason"], a.phase)
            elif a.phase > e["orig"]:
                decide(e, "moved", e["rule"], e["reason"], a.phase)
            else:
                decide(e, "kept", "ok", "passes sector fit, do-not-touch, prerequisite and readiness checks", a.phase)
    kept.sort(key=lambda a: a.phase)
    return kept, decisions


def place_requests(request_ids: list[str], plan_actions: list[PlanAction], client) -> list[GuardrailDecision]:
    """Each leadership request is a pseudo-action at Phase 1 placed against the winning plan."""
    out = []
    for rid in request_ids:
        item = CATALOG[rid]
        pseudo = PlanAction(action=f"Leadership request: {item['name']}", intervention_id=rid, phase=1,
                            target_scope="company-wide", addresses=[], evidence=[])
        _, ds = place(list(plan_actions) + [pseudo], client, ["plan"] * len(plan_actions) + ["leadership_request"])
        d = next(d for d in ds if d.source == "leadership_request")
        if d.decision == "moved":
            d.reason = f"deferred to Phase {d.to_phase}: {d.reason}"
        elif d.decision == "kept":
            d.reason = "adopted in Phase 1: " + d.reason
        out.append(d)
    return out
