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
  focus: FocusInfo | null; audience: Audience; request: Record<string, unknown>; protected?: string[];
  degraded?: string[]; briefs?: Partial<Record<Audience, Brief>>;
}
export type Pillar = "branding" | "recruiting" | "advocacy" | "retention";
export type FocusLevel = "less" | "normal" | "more";
export type Focus = Record<Pillar, FocusLevel>;
export type Audience = "hr" | "cfo" | "board";
export const PILLARS: { id: Pillar; label: string }[] = [
  { id: "branding", label: "Employer branding & reputation" }, { id: "recruiting", label: "Recruiting & talent attraction" },
  { id: "advocacy", label: "Employee advocacy" }, { id: "retention", label: "Retention & internal climate" }];
export const AUDIENCES: { id: Audience; label: string }[] = [
  { id: "hr", label: "HR Manager" }, { id: "cfo", label: "CFO" }, { id: "board", label: "Board members / Stakeholders" }];
export const NEUTRAL: Focus = { branding: "normal", recruiting: "normal", advocacy: "normal", retention: "normal" };

/** Live warning shown under the priority switches (the backend applies the same rule). */
export function focusWarning(f: Focus): string | null {
  const v = Object.values(f);
  if (v.every((x) => x === "less")) return "Every pillar is on Less. Priorities are relative, so lowering everything leaves the root causes unaddressed and the result would not be effective. The engine will use Normal for all pillars.";
  if (v.every((x) => x === "more")) return "Every pillar is on More: priorities are relative, so this is the same as Normal everywhere.";
  if (v.filter((x) => x === "less").length === 3) return "Three pillars are on Less: the plan will concentrate on one pillar only and may be much less effective overall.";
  return null;
}

export interface FocusInfo { requested: Record<string, string>; effective: Record<string, string>; warnings: string[]; deferred: string[]; added_symptoms: string[] }
export interface PriorityRow { problem: string; label: string; pillar: string; role: string; weight_before: number; weight_after: number; rank_before: number; rank_after: number }
export interface WhatIfResult {
  focus: FocusInfo; priorities: PriorityRow[]; plan_before: ScheduledAction[]; plan_after: ScheduledAction[];
  diff: { added: string[]; removed: string[]; moved: string[] }; roi_before: RoiResult; roi_after: RoiResult;
  unchanged_rules: string[]; summary: string[];
}
export interface RequestVerdict { action: string; label: string; plain: string; verdict: "yes_now" | "already_planned" | "later" | "no"; headline: string; reason: string; phase: number | null; evidence: SourceV2[]; paths: string[]; precedents: string[] }
export interface RequestCheck { text: string; understood: boolean; matches: RequestVerdict[]; suggestions: { action: string; label: string }[]; note: string }

export interface RunStateV2 { run_id: string; status: "queued" | "running" | "done" | "error"; stage: string | null; stages_done: string[]; error: string | null; result: ResultV2 | null }
