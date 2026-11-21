import type { GuardrailDecision, RoiResult } from "./types";

export interface MetricCheck { key: string; label: string; unit: string; value: number; peer: number | null; status: string; gap_pct: number | null; thresholds: string[] }
export interface SourceV2 { kind: string; ref: string; quote: string }
export interface ProblemSignal { problem: string; label: string; plain: string; pillar: string; measured: MetricCheck[]; healthy: MetricCheck[]; text: SourceV2[]; severity: number; status: string; reason: string }
export interface CauseLink { source: string; target: string; strength: number; mechanism: string; origin: "reference" | "client_text"; evidence: SourceV2[] }
export interface RootCauseV2 { problem: string; label: string; plain: string; role: "root" | "symptom" | "standalone" | "intermediate"; weight: number; causes: string[]; caused_by: string[]; relation: number; prominence: number }
export interface ScheduledAction { action: string; label: string; plain: string; phase: number; scope: string; fixes: string[]; why_now: string; evidence: string[]; precedents: string[]; original: boolean; source: string; rationale: string; paths: string[] }
export interface PlanV2 { plan_id: string; title: string; thesis: string; variant: string; actions: ScheduledAction[]; decisions: GuardrailDecision[]; dropped: { action: string; justification: string }[]; coverage: number; evidence_strength: number; cost_eur: number; det_score: number; jury_score: number | null; final: number | null }
export interface CriticIssue { plan_id: string; target: string; kind: string; severity: "blocking" | "minor"; detail: string; fix: string; by: "rules" | "llm" }
export interface CriticRound { round: number; issues: CriticIssue[]; verdict: "pass" | "revise" }
export interface RubricScore { plan_id: string; feasibility: number; impact: number; evidence: number; risk: number; cites: string[]; concern: string; verdict: string }
export interface JurorBallot { persona: string; scores: RubricScore[] }
export interface JuryAudit { weights: Record<string, number>; flags: string[]; plan_scores: Record<string, number>; margin: number; decided_by: string }
export interface Confidence { problem: string; level: "high" | "medium" | "low"; metric_evidence: number; text_evidence: number; literature: number; precedents: number; reason: string }
export interface CaseRank { case: string; name: string; score: number; shared_problems: string[]; shared_actions: string[]; worker_fit: boolean; outcome: string; reason: string }
export interface Brief { headline: string; one_minute: { title: string; text: string; detail?: string }[]; sections: { heading: string; text: string }[]; writer: "llm_verified" | "template"; dropped_sentences: string[]; glossary: Record<string, string> }
export interface Stability { fingerprint: string; signature: string; previous_runs: number; same_as_previous: boolean | null; differences: string[] }
export interface TraceV2 { stage: string; seconds: number; kind: string; models: string[]; cached: boolean; notes: string[] }
export interface Challenge { problem: string; verdict: string; reason: string }

export interface ResultV2 {
  engine: "v2";
  client: { company_name: string; industry: string; archetypes: string[]; healthy_baselines: string[]; noise: { field: string; sentence: string; reason: string }[];
            readiness: { gate_open: boolean; reasons: string[] }; segments: { name: string; rating: number; flag: string }[] };
  problems: ProblemSignal[]; challenges: Challenge[];
  roots: { ids: string[]; links: CauseLink[]; causes: RootCauseV2[] };
  cases: CaseRank[]; plans: PlanV2[]; winner: string; critic_rounds: CriticRound[];
  ballots: JurorBallot[]; jury_audit: JuryAudit | null;
  leadership: GuardrailDecision[]; leadership_views: Record<string, string>;
  roi: RoiResult; confidence: Confidence[]; brief: Brief; stability: Stability;
  documents: Record<string, { kind: string; title: string; text: string }>;
  labels: Record<string, string>; trace: TraceV2[];
}
export interface RunStateV2 { run_id: string; status: "queued" | "running" | "done" | "error"; stage: string | null; stages_done: string[]; error: string | null; result: ResultV2 | null }
