from typing import Literal, Optional
from pydantic import BaseModel, Field

PillarId = Literal["branding", "recruiting", "advocacy", "retention"]
Status = Literal["better", "worse", "in_line", "no_benchmark"]


# ---------- Track A (internal) ----------
class InterventionStep(BaseModel):
    step: int
    text: str
    intervention_ids: list[str]


class CaseStudy(BaseModel):
    id: str; name: str; sector_profile: str; archetypes: list[str]
    problem: str
    problem_concepts: list[str]
    interventions: list[InterventionStep]
    intervention_ids: list[str]
    measured_roi_text: str
    kpis_t0: dict[str, float]; kpis_t1: dict[str, float]
    kpi_deltas: dict[str, float]


class Snippet(BaseModel):
    id: str; source: str; finding: str; concepts: list[str]; archetypes: list[str]


class FieldNote(BaseModel):
    id: str; title: str; text: str; concepts: list[str]


# ---------- Track B (client) ----------
class MetricRow(BaseModel):
    key: str; value: float; peer: Optional[float]; status: Status; section: str


class Segment(BaseModel):
    name: str; reviews: int; rating: float; flag: Literal["weak", "strong", "normal"]


class NoiseFlag(BaseModel):
    field: str; sentence: str; reason: str


class Readiness(BaseModel):
    gate_open: bool; say_do_gap_active: bool; management_friction: bool; burnout_signal: bool
    organic_advocacy_present: bool; unknown: bool; reasons: list[str]


class ClientProfile(BaseModel):
    scenario_code: str; company_name: str; industry: str; workforce_target: str
    headcount: Optional[int]; locations_count: Optional[int]; declared_evp: Optional[str]
    archetypes: list[str]
    signals: dict[str, str]
    internal: dict[str, str]
    narrative: str
    metrics: dict[str, MetricRow]
    segments: list[Segment]
    noise: list[NoiseFlag]
    readiness: Readiness
    healthy_baselines: list[str]
    annual_agency_spend_eur: Optional[float]
    leadership_requests: list[str]


# ---------- LLM outputs ----------
class Evidence(BaseModel):
    kind: Literal["metric", "text"]; ref: str; quote: str


class Finding(BaseModel):
    id: str; statement: str; severity: int = Field(ge=1, le=3); scope: str; evidence: list[Evidence]


class PillarAnalysis(BaseModel):
    pillar: PillarId; findings: list[Finding]; healthy_signals: list[str]; open_questions: list[str]


class Hypothesis(BaseModel):
    id: str; statement: str; pillars: list[PillarId]; concepts: list[str]
    supporting_finding_ids: list[str]; evidence: list[Evidence]; affected_scope: str


class HypothesisSet(BaseModel):
    hypotheses: list[Hypothesis]


class Refutation(BaseModel):
    hypothesis_id: str; verdict: Literal["supported", "weakened", "refuted"]
    severity: Literal["none", "non_critical", "critical"]; reason: str; counter_evidence: list[Evidence]


class ConfutationSet(BaseModel):
    refutations: list[Refutation]


class CausalEdge(BaseModel):
    source: str; target: str; strength: int = Field(ge=0, le=3); mechanism: str; field_notes: list[str]


class CausalMap(BaseModel):
    edges: list[CausalEdge]


class MatchRating(BaseModel):
    case_id: str; relevance: int = Field(ge=0, le=3); reason: str


class MatchRatings(BaseModel):
    root_cause_id: str; ratings: list[MatchRating]


class PlanAction(BaseModel):
    action: str; intervention_id: str
    phase: int = Field(ge=1, le=3); target_scope: str
    addresses: list[str]; evidence: list[str]


class LeadershipResponse(BaseModel):
    request: str; decision: Literal["adopt", "defer", "reject"]; reason: str


class CandidatePlan(BaseModel):
    plan_id: str; title: str; thesis: str; actions: list[PlanAction]
    leadership_responses: list[LeadershipResponse]; do_not_touch: list[str]; open_questions: list[str]


class CandidatePlans(BaseModel):
    plans: list[CandidatePlan]


class PlanVote(BaseModel):
    plan_id: str
    feasibility: int = Field(ge=1, le=10); impact: int = Field(ge=1, le=10); risk: int = Field(ge=1, le=10)
    concern: str; verdict: str


class JuryVerdict(BaseModel):
    persona: str; votes: list[PlanVote]


# ---------- Deterministic results ----------
class GuardrailDecision(BaseModel):
    subject: str
    intervention_id: str
    source: Literal["plan", "leadership_request", "noise", "auto_added"]
    decision: Literal["kept", "moved", "blocked", "deferred_beyond_plan", "added"]
    from_phase: Optional[int]; to_phase: Optional[int]
    rule: str
    reason: str


class RootCause(BaseModel):
    hypothesis: Hypothesis; prominence: float; relation: float; weight: float
    is_root: bool; refutation: Optional[Refutation]


class Alignment(BaseModel):
    row_ids: list[str]; col_ids: list[str]; values: list[list[float]]
    components: dict[str, list[list[float]]]


class ScoredPlan(BaseModel):
    plan: CandidatePlan; decisions: list[GuardrailDecision]
    coverage: float; evidence: float; penalty: float; pre_score: float
    jury: Optional[float] = None; final: Optional[float] = None
    votes: list[tuple[str, PlanVote]] = []


class RoiLine(BaseModel):
    name: str; applies: bool; base_value: Optional[float]
    expected_change: Optional[float]; conservative_change: Optional[float]
    benefit_expected_eur: float; benefit_conservative_eur: float
    precedent_case_ids: list[str]; formula: str


class RoiResult(BaseModel):
    lines: list[RoiLine]; cost_eur: float; benefit_expected_eur: float; benefit_conservative_eur: float
    roi_expected: Optional[float]; roi_conservative: Optional[float]; payback_months_expected: Optional[float]


class KpiProjection(BaseModel):
    key: str; t0: float; peer: Optional[float]; projected: Optional[float]; change: Optional[float]


class StageTrace(BaseModel):
    stage: str; seconds: float; models: list[str]; cached: bool; notes: list[str]


class PipelineResult(BaseModel):
    client: ClientProfile
    pillar_analyses: list[PillarAnalysis]
    hypotheses: list[Hypothesis]; dropped_hypotheses: list[dict]
    refutations: list[Refutation]
    causal_edges: list[CausalEdge]
    influence_ids: list[str]; influence_matrix: list[list[float]]
    root_causes: list[RootCause]
    case_alignment: Alignment; snippet_alignment: Alignment
    top_cases: list[dict]; top_snippets: list[dict]; field_notes: list[dict]
    candidates: list[ScoredPlan]
    ranked: list[ScoredPlan]
    leadership_decisions: list[GuardrailDecision]
    roi: RoiResult; kpis: list[KpiProjection]
    trace: list[StageTrace]


class RunRequest(BaseModel):
    scenario_code: Optional[str] = None
    scenario: Optional[dict] = None
    snapshot: Optional[dict] = None
    overrides: Optional[dict] = None


class RunState(BaseModel):
    run_id: str; status: Literal["queued", "running", "done", "error"]
    stage: Optional[str] = None; stages_done: list[str] = []
    error: Optional[str] = None; result: Optional[PipelineResult] = None
