"""Pydantic models of engine v2. Tool results are deterministic; agent outputs are LLM JSON that Python verifies."""
from typing import Literal, Optional
from pydantic import BaseModel, Field

from ..schemas import ClientProfile, GuardrailDecision, RoiResult, KpiProjection


# ---------- evidence ----------
class Source(BaseModel):
    """One piece of evidence. ref = metric key, client text ref (signals.x / internal.x / narrative) or doc id (C05, R1, FN4)."""
    kind: Literal["metric", "client_text", "document", "catalog", "analyst_mapping"]
    ref: str
    quote: str = ""
    verified: bool = True


class QuoteCheck(BaseModel):
    ok: bool; ref: str; quote: str; reason: str = ""


# ---------- tool results ----------
class ConceptHit(BaseModel):
    concept: str; synonym: str; label: str


class Relevance(BaseModel):
    item: str; kind: str; relevant: bool; reason: str; path: list[str] = []


class MetricCheck(BaseModel):
    key: str; label: str; unit: str; value: float; peer: Optional[float]
    status: str; gap_pct: Optional[float]
    thresholds: list[str] = []          # human sentences, each with its source id


class ProblemSignal(BaseModel):
    """A problem detected for this client by check_metrics (deterministic)."""
    problem: str; label: str; plain: str; pillar: str
    measured: list[MetricCheck] = []    # worse-than-peer or over-threshold indicators
    healthy: list[MetricCheck] = []     # indicators better than peers (counter-evidence)
    text: list[Source] = []             # verbatim client sentences mentioning the problem
    severity: float = 0.0               # 0..1, from gaps and thresholds
    status: Literal["confirmed", "text_only", "healthy", "out_of_scope"] = "confirmed"
    reason: str = ""


class CauseLink(BaseModel):
    source: str; target: str; strength: int; mechanism: str
    origin: Literal["reference", "client_text"]; evidence: list[Source]


class RootCauseV2(BaseModel):
    problem: str; label: str; plain: str
    role: Literal["root", "symptom", "standalone", "intermediate"]
    drives: float; driven_by: float; prominence: float; relation: float; weight: float
    causes: list[str] = []; caused_by: list[str] = []


class RootCauseResult(BaseModel):
    ids: list[str]; matrix: list[list[float]]; links: list[CauseLink]; causes: list[RootCauseV2]


class Gate(BaseModel):
    action: str; allowed: bool; earliest_phase: int = 1
    rule: str = "ok"; reason: str = ""; evidence: list[Source] = []


class CaseRank(BaseModel):
    case: str; name: str; score: float; shared_problems: list[str]; shared_actions: list[str]
    worker_fit: bool; outcome: str; reason: str


class ScheduledAction(BaseModel):
    action: str; label: str; plain: str; phase: int; scope: str = "company-wide"
    fixes: list[str] = []; why_now: str = ""; evidence: list[str] = []
    precedents: list[str] = []; original: bool = False; source: str = "plan"
    rationale: str = ""; paths: list[str] = []


# ---------- agent outputs (LLM JSON, verified by Python) ----------
class Quote(BaseModel):
    ref: str = Field(description="exact client text ref: signals.<key>, internal.<key> or narrative")
    quote: str = Field(description="verbatim substring of that field")


class ProblemView(BaseModel):
    problem: str = Field(description="problem id from the candidate list")
    agree: bool = Field(description="true if the data supports this problem for this client")
    scope: str = Field(description="who is affected: company-wide or named cohorts/sites")
    explanation: str = Field(description="one or two plain-language sentences, no numbers")
    quotes: list[Quote] = []


class Diagnosis(BaseModel):
    pillar: str; problems: list[ProblemView]


class Challenge(BaseModel):
    problem: str
    verdict: Literal["holds", "weaker", "refuted"]
    reason: str
    counter_quotes: list[Quote] = []


class SkepticReport(BaseModel):
    challenges: list[Challenge]


class PlanChoice(BaseModel):
    action: str = Field(description="catalog action id from the allowed list")
    scope: str = Field(description="who it targets: company-wide or named cohorts/sites")
    why: str = Field(description="one plain sentence, no numbers")


class OriginalIdea(BaseModel):
    title: str; description: str
    fixes: list[str] = Field(description="problem ids it addresses")
    evidence: list[str] = Field(description="document ids (C.., R.., FN..) that support it")
    phase: int = Field(ge=1, le=3)


class RequestView(BaseModel):
    request: str = Field(description="leadership request action id")
    explanation: str = Field(description="plain-language explanation of the verdict given by the rules")


class DroppedAction(BaseModel):
    action: str; justification: str


class StrategyDraft(BaseModel):
    plan_id: str; title: str; thesis: str
    choices: list[PlanChoice]; original_ideas: list[OriginalIdea] = []
    dropped: list[DroppedAction] = []
    request_views: list[RequestView] = []


class StrategyDrafts(BaseModel):
    plans: list[StrategyDraft]


class CriticIssue(BaseModel):
    plan_id: str; target: str = ""
    kind: Literal["unsupported_claim", "missing_coverage", "rule_violation", "unjustified_drop",
                  "original_unsupported", "scope_problem", "contradiction", "other"]
    severity: Literal["blocking", "minor"]
    detail: str; fix: str = ""
    by: Literal["rules", "llm"] = "llm"


class CriticReview(BaseModel):
    issues: list[CriticIssue] = []


class RubricScore(BaseModel):
    plan_id: str
    feasibility: int = Field(ge=1, le=5); impact: int = Field(ge=1, le=5)
    evidence: int = Field(ge=1, le=5); risk: int = Field(ge=1, le=5, description="5 = very risky")
    cites: list[str] = Field(description="action ids or document ids from that plan that justify the scores")
    concern: str; verdict: Literal["approve", "approve_with_changes", "reject"]


class JurorBallot(BaseModel):
    persona: str; scores: list[RubricScore]


class ReportSection(BaseModel):
    heading: str; text: str = Field(description="plain language, may use {{tokens}} and [ID] citations, no digits")


class ReportDraft(BaseModel):
    headline: str; sections: list[ReportSection]


# ---------- assembled results ----------
class PlanV2(BaseModel):
    plan_id: str; title: str; thesis: str; variant: str
    actions: list[ScheduledAction]; decisions: list[GuardrailDecision] = []
    dropped: list[DroppedAction] = []
    coverage: float = 0.0; evidence_strength: float = 0.0; cost_eur: float = 0.0
    det_score: float = 0.0; jury_score: Optional[float] = None; final: Optional[float] = None


class CriticRound(BaseModel):
    round: int; issues: list[CriticIssue]; verdict: Literal["pass", "revise"]


class JuryAudit(BaseModel):
    weights: dict[str, float]; flags: list[str]; plan_scores: dict[str, float]
    margin: float; decided_by: Literal["jury", "deterministic_tiebreak"]


class Stability(BaseModel):
    fingerprint: str; signature: str; previous_runs: int
    same_as_previous: Optional[bool]; differences: list[str] = []


class Confidence(BaseModel):
    problem: str; level: Literal["high", "medium", "low"]; metric_evidence: int; text_evidence: int
    literature: int; precedents: int; reason: str


class Brief(BaseModel):
    """The readable layer: everything the UI needs to explain the answer without the raw data."""
    headline: str
    one_minute: list[dict]              # [{title, text}]
    sections: list[ReportSection]
    writer: Literal["llm_verified", "template"]
    dropped_sentences: list[str] = []
    glossary: dict[str, str]


class TraceV2(BaseModel):
    stage: str; seconds: float; kind: Literal["tool", "agent", "critic"]; models: list[str] = []
    cached: bool = False; notes: list[str] = []


class ResultV2(BaseModel):
    engine: str = "v2"
    client: ClientProfile
    problems: list[ProblemSignal]
    diagnoses: list[Diagnosis]; challenges: list[Challenge]
    roots: RootCauseResult
    cases: list[CaseRank]
    plans: list[PlanV2]; winner: str
    critic_rounds: list[CriticRound]
    ballots: list[JurorBallot]; jury_audit: Optional[JuryAudit]
    leadership: list[GuardrailDecision]; leadership_views: dict[str, str]
    roi: RoiResult; kpis: list[KpiProjection]
    confidence: list[Confidence]
    brief: Brief
    stability: Stability
    documents: dict[str, dict]          # id -> {title, text} for every cited document
    labels: dict[str, str]              # id -> plain label (problems, actions, metrics, cases)
    trace: list[TraceV2]


class RunStateV2(BaseModel):
    run_id: str; status: Literal["queued", "running", "done", "error"]
    stage: Optional[str] = None; stages_done: list[str] = []
    error: Optional[str] = None; result: Optional[ResultV2] = None
