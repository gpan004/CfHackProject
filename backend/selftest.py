"""Plain-assert tests for the deterministic logic (§12). Run: python -m backend.selftest phase1|phase2"""
import sys

import numpy as np

from .causal import dematel, root_cause_flags
from .schemas import (MetricRow, Readiness, ClientProfile, PlanAction, CaseStudy)

EXPECTED_CASES = {
    "C01": {"reputation_audit", "persona_calibration", "evp_realignment", "board_risk_dashboard"},
    "C02": {"ambassador_selection", "ambassador_tracking", "board_risk_dashboard"},
    "C03": {"persona_calibration", "technical_storytelling", "evp_realignment"},
    "C04": {"portal_ux_audit", "persona_calibration", "mobile_fast_apply", "persona_aligned_jds"},
    "C05": {"internal_listening_360", "reputation_audit", "manager_coaching", "career_framework", "evp_realignment",
            "board_risk_dashboard", "persona_aligned_jds", "ambassador_selection"},
    "C06": {"portal_ux_audit", "reputation_audit", "persona_calibration", "mobile_fast_apply", "evp_realignment", "persona_aligned_jds"},
    "C07": {"internal_listening_360", "portal_ux_audit", "persona_calibration", "retail_shift_rotation", "manager_coaching",
            "mobile_fast_apply", "persona_aligned_jds", "ambassador_selection"},
    "C08": {"reputation_audit", "persona_calibration", "evp_realignment", "board_risk_dashboard", "ambassador_selection", "ambassador_tracking"},
    "C09": {"candidate_feedback_digitization", "persona_calibration", "ambassador_selection", "ambassador_tracking", "board_risk_dashboard"},
    "C10": {"portal_ux_audit", "reputation_audit", "internal_listening_360", "mobile_fast_apply", "retail_shift_rotation", "board_risk_dashboard"},
    "C11": {"candidate_feedback_digitization", "reputation_audit", "evp_realignment", "ambassador_tracking"},
}
KW, FL, FR, CC = "knowledge_worker", "frontline_logistics", "frontline_retail", "clinical_care"


def clients():
    from .ingest import scenarios, client_for
    return [client_for(s["scenario_code"]) for s in scenarios()]


def phase1():
    from .ingest import track_a
    a = track_a()
    cs = clients()
    assert len(a["cases"]) == 11 and len(a["snippets"]) == 10 and len(a["field_notes"]) == 6 and len(cs) == 3
    for c in a["cases"]:
        assert set(c.intervention_ids) == EXPECTED_CASES[c.id], (c.id, c.intervention_ids)
    assert [c.archetypes for c in cs] == [[KW], [FL], [CC]], [c.archetypes for c in cs]
    exp_arch = {**{k: [KW] for k in ("C01", "C02", "C03", "C05", "C09")}, **{k: [FR] for k in ("C04", "C07", "C10")},
                "C06": [FL], "C08": [CC], "C11": [CC]}
    for c in a["cases"]:
        assert c.archetypes == exp_arch[c.id], (c.id, c.archetypes)
    scopes = {s.id: s.archetypes for s in a["snippets"]}
    exp_s = {"R2": [FL, FR, CC], "R6": [KW], "R7": [FL, FR], "R10": [FR]}
    for sid, arch in scopes.items():
        assert sorted(arch) == sorted(exp_s.get(sid, [])), (sid, arch)
    A, B, C = cs
    assert len(A.noise) == 1 and "shift rotation" in A.noise[0].sentence.lower(), A.noise
    assert len(B.noise) == 0 and len(C.noise) == 0
    assert B.annual_agency_spend_eur == 760000 and A.annual_agency_spend_eur is None and C.annual_agency_spend_eur is None
    assert A.leadership_requests == ["ambassador_selection", "compensation_review", "retail_shift_rotation"], A.leadership_requests
    assert B.leadership_requests == ["technical_storytelling", "mobile_fast_apply", "persona_aligned_jds"], B.leadership_requests
    assert C.leadership_requests == ["evp_realignment", "ambassador_tracking"], C.leadership_requests
    weak = lambda c: {s.name for s in c.segments if s.flag == "weak"}
    assert weak(A) == {"Milan_Product_Squads", "Berlin_Product_Squads"}, weak(A)
    assert len(weak(B)) == 3 and all(any(h in n for n in weak(B)) for h in ("Rome", "Bologna", "Naples")), weak(B)
    assert weak(C) == {"Outdated_Profile_Regional_Clinics_18_Sites"}, weak(C)
    print("phase1 OK")


def phase2_pure():
    W = np.array([[0, 1, 1], [0, 0, 1], [0, 0, 0]], float)
    _, _, prom, rel = dematel(W)
    assert np.argmax(rel) == 0 and np.argmin(rel) == 2
    _, _, prom, rel = dematel(np.zeros((3, 3)))
    roots, w = root_cause_flags(prom, rel)
    assert roots == [True] * 3 and np.allclose(w, 1 / 3)

    # ROI hand calculation
    from . import metrics
    m = lambda k, v: MetricRow(key=k, value=v, peer=None, status="no_benchmark", section="x")
    rd = Readiness(gate_open=True, say_do_gap_active=False, management_friction=False, burnout_signal=False,
                   organic_advocacy_present=False, unknown=False, reasons=[])
    cl = ClientProfile(scenario_code="T", company_name="T", industry="", workforce_target="", headcount=None, locations_count=None,
                       declared_evp=None, archetypes=[KW], signals={}, internal={}, narrative="",
                       metrics={"estimated_annual_attrition_exposure_eur": m("estimated_annual_attrition_exposure_eur", 1_000_000),
                                "manual_hr_tracking_hours_month": m("manual_hr_tracking_hours_month", 100)},
                       segments=[], noise=[], readiness=rd, healthy_baselines=[], annual_agency_spend_eur=None, leadership_requests=[])
    case = lambda i, ivs, d: CaseStudy(id=i, name=i, sector_profile="", archetypes=[KW], problem="", problem_concepts=[], interventions=[],
                                       intervention_ids=ivs, measured_roi_text="", kpis_t0={}, kpis_t1={}, kpi_deltas=d)
    cases = [case("X1", ["manager_coaching"], {"estimated_annual_attrition_exposure_eur": -0.4}),
             case("X2", ["manager_coaching"], {"estimated_annual_attrition_exposure_eur": -0.2}),
             case("X3", ["ambassador_tracking"], {"manual_hr_tracking_hours_month": -0.5})]
    acts = [PlanAction(action="a", intervention_id=i, phase=1, target_scope="all", addresses=[], evidence=[])
            for i in ("manager_coaching", "internal_listening_360", "original")]
    r = metrics.roi(acts, cases, cl)
    att = next(l for l in r.lines if l.name == "attrition_exposure")
    assert abs(att.benefit_expected_eur - 300_000) < 1e-6 and abs(att.benefit_conservative_eur - 200_000) < 1e-6
    assert r.cost_eur == 60000 + 15000 + 10000
    assert abs(r.roi_expected - (300_000 - 85_000) / 85_000) < 1e-9
    assert not next(l for l in r.lines if l.name == "hr_hours").applies
    print("phase2 (pure) OK")


def phase2():
    phase2_pure()
    from .guardrails import place_requests
    from .ingest import track_a
    A, B, C = clients()
    assert not A.readiness.gate_open and not A.readiness.organic_advocacy_present
    assert any("1.3" in x and "R1" in x for x in A.readiness.reasons) and any("2.64" in x for x in A.readiness.reasons), A.readiness.reasons
    assert B.readiness.gate_open and not B.readiness.organic_advocacy_present
    assert C.readiness.gate_open and C.readiness.organic_advocacy_present

    def verdicts(c):
        return {d.intervention_id: (d.decision, d.to_phase, d.rule) for d in place_requests(c.leadership_requests, [], c)}
    va, vb, vc = verdicts(A), verdicts(B), verdicts(C)
    assert va["ambassador_selection"] == ("moved", 3, "readiness_gate"), va
    assert va["compensation_review"][0:1] == ("blocked",) and va["compensation_review"][2] == "do_not_touch", va
    assert va["retail_shift_rotation"][2] == "sector_fit", va
    assert vb["technical_storytelling"][2] == "sector_fit", vb
    assert vb["mobile_fast_apply"] == ("moved", 2, "prerequisite"), vb
    assert vb["persona_aligned_jds"] == ("moved", 2, "prerequisite"), vb
    assert vc["evp_realignment"][2] == "do_not_touch", vc
    assert vc["ambassador_tracking"] == ("moved", 2, "prerequisite"), vc

    a = track_a()
    case_arch = {c.id: c.archetypes for c in a["cases"]}
    for cl, banned_snip in ((A, "R10"), (B, "R6")):
        fit = [1.0 if (not c.archetypes or set(c.archetypes) & set(cl.archetypes)) else 0.0 for c in a["cases"]]
        snip_fit = {s.id: (not s.archetypes or bool(set(s.archetypes) & set(cl.archetypes))) for s in a["snippets"]}
        assert not snip_fit[banned_snip]
        if cl is A:
            assert all(f == 0 for c, f in zip(a["cases"], fit) if set(case_arch[c.id]) & {FR, FL})
    print("phase2 OK")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("phase1", "all"):
        phase1()
    if which in ("phase2", "all"):
        phase2()
    if which == "pure":
        phase2_pure()
