export type Phase = 1 | 2 | 3;
export interface Evidence { kind: "metric" | "text"; ref: string; quote: string }
export interface PlanAction { action: string; intervention_id: string; phase: Phase; target_scope: string; addresses: string[]; evidence: string[] }
export interface CandidatePlan { plan_id: string; title: string; thesis: string; actions: PlanAction[]; do_not_touch: string[]; open_questions: string[] }
export interface GuardrailDecision { subject: string; intervention_id: string; source: string; decision: "kept" | "moved" | "blocked" | "deferred_beyond_plan" | "added"; from_phase: number | null; to_phase: number | null; rule: string; reason: string }
export interface PlanVote { plan_id: string; feasibility: number; impact: number; risk: number; concern: string; verdict: string }
export interface ScoredPlan { plan: CandidatePlan; decisions: GuardrailDecision[]; coverage: number; evidence: number; penalty: number; pre_score: number; jury: number | null; final: number | null; votes: [string, PlanVote][] }
export interface RootCause { hypothesis: { id: string; statement: string; pillars: string[]; affected_scope: string }; prominence: number; relation: number; weight: number; is_root: boolean }
export interface Alignment { row_ids: string[]; col_ids: string[]; values: number[][] }
export interface RoiLine { name: string; applies: boolean; base_value: number | null; expected_change: number | null; benefit_expected_eur: number; benefit_conservative_eur: number; precedent_case_ids: string[]; formula: string }
export interface RoiResult { lines: RoiLine[]; cost_eur: number; benefit_expected_eur: number; benefit_conservative_eur: number; roi_expected: number | null; roi_conservative: number | null; payback_months_expected: number | null }
export interface KpiProjection { key: string; t0: number; peer: number | null; projected: number | null; change: number | null }
export interface PipelineResult {
  client: { company_name: string; industry: string; archetypes: string[]; healthy_baselines: string[]; noise: { field: string; sentence: string; reason: string }[];
            readiness: { gate_open: boolean; reasons: string[] }; segments: { name: string; rating: number; flag: string }[] };
  influence_ids: string[]; influence_matrix: number[][]; root_causes: RootCause[];
  case_alignment: Alignment; top_cases: { id: string; name: string; score: number; measured_roi_text: string; kpi_deltas: Record<string, number> }[];
  top_snippets: { id: string; source: string; finding: string; score: number }[];
  field_notes: { id: string; title: string; text: string }[];
  ranked: ScoredPlan[]; leadership_decisions: GuardrailDecision[]; roi: RoiResult; kpis: KpiProjection[];
  trace: { stage: string; seconds: number; models: string[]; cached: boolean; notes: string[] }[];
}
export interface RunState { run_id: string; status: "queued" | "running" | "done" | "error"; stage: string | null; stages_done: string[]; error: string | null; result: PipelineResult | null }
export interface ScenarioInfo { scenario_code: string; company_name: string; industry: string }
