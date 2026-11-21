import { useState } from "react";
import type { GuardrailDecision, PipelineResult, ScoredPlan } from "../types";
import Charts from "./Charts";

const eur = (v: number) => "€" + Math.round(v).toLocaleString("en-US");
const pct = (v: number | null) => (v == null ? "–" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(0)}%`);

function Section({ id, eyebrow, title, children }: { id?: string; eyebrow: string; title: string; children: React.ReactNode }) {
  return (
    <section id={id} className="scroll-mt-28">
      <p className="eyebrow">{eyebrow}</p>
      <h2 className="section-title mt-2">{title}</h2>
      <div className="mt-5">{children}</div>
    </section>
  );
}

function PlanPhases({ sp, r, compact = false }: { sp: ScoredPlan; r: PipelineResult; compact?: boolean }) {
  const hover: Record<string, string> = {};
  r.top_cases.forEach((c) => (hover[c.id] = `${c.name}: ${c.measured_roi_text}`));
  r.top_snippets.forEach((s) => (hover[s.id] = `${s.source}: ${s.finding}`));
  r.field_notes?.forEach((f) => (hover[f.id] = `${f.title}: ${f.text}`));
  const badge = (a: { action: string }) => {
    const d = sp.decisions.find((x) => x.subject === a.action && (x.decision === "moved" || x.decision === "added"));
    if (!d) return null;
    return <span className="chip">{d.decision === "added" ? "added prerequisite" : `moved from P${d.from_phase}`}</span>;
  };
  return (
    <div className="grid gap-4 md:grid-cols-3">
      {[1, 2, 3].map((ph) => (
        <div key={ph} className={compact ? "rounded-xl border border-slate-200 bg-white p-4" : "card"}>
          <p className="eyebrow">0{ph}. Phase {ph}</p>
          <ul className="mt-3 space-y-3">
            {sp.plan.actions.filter((a) => a.phase === ph).map((a, i) => (
              <li key={i} className="rounded-xl border border-slate-200 bg-white p-3">
                <div className="flex flex-wrap items-start gap-2">
                  <span className="font-semibold leading-snug">{a.action}</span>
                  {badge(a)}
                </div>
                <p className="mt-1 text-[13px] text-ink/60">{a.target_scope}</p>
                {!compact && a.evidence.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {a.evidence.map((e) => (
                      <span key={e} title={hover[e] ?? e} className="cursor-help rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] font-semibold text-ink/70">{e}</span>
                    ))}
                  </div>
                )}
              </li>
            ))}
            {sp.plan.actions.every((a) => a.phase !== ph) && <li className="text-sm text-ink/40">No action</li>}
          </ul>
        </div>
      ))}
    </div>
  );
}

function DecisionRow({ d, label }: { d: GuardrailDecision; label?: string }) {
  const tone = d.decision === "blocked" || d.decision === "deferred_beyond_plan" ? "bg-red-50 text-red-700 border-red-200"
    : d.decision === "moved" ? "bg-amber-50 text-amber-700 border-amber-200" : "bg-emerald-50 text-emerald-700 border-emerald-200";
  const word = d.decision === "moved" ? `deferred to P${d.to_phase}` : d.decision === "kept" ? "adopted" : d.decision.replace(/_/g, " ");
  return (
    <li className="flex flex-col gap-1 border-b border-slate-200 py-3 last:border-0 sm:flex-row sm:items-start sm:gap-4">
      <span className={`w-fit shrink-0 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wider ${tone}`}>{word}</span>
      <div>
        <p className="font-semibold">{label ?? d.subject}</p>
        <p className="text-[13px] text-ink/70">{d.reason} <span className="text-ink/40">[{d.rule}]</span></p>
      </div>
    </li>
  );
}

export default function StrategyView({ r, runId }: { r: PipelineResult; runId: string }) {
  const [openAlt, setOpenAlt] = useState<string | null>(null);
  const [showTrace, setShowTrace] = useState(false);
  const win = r.ranked[0];
  const c = r.client;
  const blockedPlan = win.decisions.filter((d) => d.decision === "blocked" || d.decision === "deferred_beyond_plan");
  const roots = r.root_causes.filter((x) => x.is_root);
  const symptoms = r.root_causes.filter((x) => !x.is_root);
  const download = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(r, null, 1)], { type: "application/json" }));
    Object.assign(document.createElement("a"), { href: url, download: `${runId}.json` }).click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-16">
      {/* 1 header */}
      <div className="card-white">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="eyebrow">{c.industry}</p>
            <h2 className="mt-2 text-[34px] font-extrabold leading-tight">{c.company_name}</h2>
            <div className="mt-3 flex flex-wrap gap-2">{c.archetypes.map((a) => <span key={a} className="chip">{a.replace("_", " ")}</span>)}</div>
          </div>
          <div className={`rounded-xl border px-4 py-3 text-sm ${c.readiness.gate_open ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"}`}>
            <p className="font-semibold">Readiness gate: {c.readiness.gate_open ? "open" : "closed"}</p>
            <ul className="mt-1 max-w-sm list-disc pl-4 text-[13px] text-ink/70">{c.readiness.reasons.map((x) => <li key={x}>{x}</li>)}</ul>
          </div>
        </div>
      </div>

      {/* 2 winning strategy */}
      <Section id="strategy" eyebrow="Winning strategy" title={win.plan.title}>
        <p className="max-w-3xl text-[16px] leading-relaxed text-ink/80">{win.plan.thesis}</p>
        <div className="mt-4 flex flex-wrap gap-3 text-sm">
          {[["Final", win.final], ["Jury", win.jury], ["Coverage", win.coverage], ["Evidence", win.evidence], ["Penalty", -win.penalty]].map(([k, v]) => (
            <span key={k as string} className="rounded-btn border border-slate-200 bg-white px-3 py-1.5"><b>{k}</b> {(v as number | null)?.toFixed(2) ?? "–"}</span>
          ))}
        </div>
        <div className="mt-6"><PlanPhases sp={win} r={r} /></div>
      </Section>

      {/* 3 blocked & deferred */}
      <Section eyebrow="Guardrails" title="Blocked & deferred">
        <div className="card">
          <ul>
            {r.leadership_decisions.map((d, i) => <DecisionRow key={"l" + i} d={d} />)}
            {blockedPlan.map((d, i) => <DecisionRow key={"p" + i} d={d} />)}
            {c.noise.map((n, i) => (
              <li key={"n" + i} className="flex flex-col gap-1 border-b border-slate-200 py-3 last:border-0 sm:flex-row sm:gap-4">
                <span className="w-fit shrink-0 whitespace-nowrap rounded-full border border-slate-300 bg-white px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-ink/60">noise</span>
                <div><p className="font-semibold">“{n.sentence}”</p><p className="text-[13px] text-ink/70">{n.reason} <span className="text-ink/40">[{n.field}]</span></p></div>
              </li>
            ))}
            {!r.leadership_decisions.length && !blockedPlan.length && !c.noise.length && <li className="text-ink/50">Nothing blocked.</li>}
          </ul>
        </div>
      </Section>

      {/* 4 root causes & do not touch */}
      <Section eyebrow="Diagnosis" title="Root causes vs symptoms">
        <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
          <div className="card space-y-3">
            {roots.map((x) => (
              <div key={x.hypothesis.id} className="rounded-xl border border-slate-200 bg-white p-4">
                <div className="flex items-center gap-2"><span className="chip">{x.hypothesis.id} · root cause</span>
                  <span className="text-xs text-ink/50">relation {x.relation.toFixed(2)} · prominence {x.prominence.toFixed(2)} · weight {x.weight.toFixed(2)}</span></div>
                <p className="mt-2 font-semibold">{x.hypothesis.statement}</p>
                <p className="text-[13px] text-ink/60">{x.hypothesis.pillars.join(", ")} · {x.hypothesis.affected_scope}</p>
              </div>
            ))}
            {symptoms.length > 0 && <p className="eyebrow pt-2">Surface symptoms</p>}
            {symptoms.map((x) => (
              <p key={x.hypothesis.id} className="text-[14px] text-ink/70"><b>{x.hypothesis.id}</b> {x.hypothesis.statement} <span className="text-ink/40">(relation {x.relation.toFixed(2)})</span></p>
            ))}
          </div>
          <div className="card">
            <p className="eyebrow">Do not touch</p>
            <ul className="mt-3 space-y-2 text-[14px]">
              {[...c.healthy_baselines, ...win.plan.do_not_touch].map((h, i) => <li key={i} className="flex gap-2"><span className="text-brand">●</span>{h}</li>)}
            </ul>
            {c.segments.some((s) => s.flag !== "normal") && <p className="eyebrow mt-5">Segments</p>}
            <ul className="mt-2 space-y-1 text-[14px]">
              {c.segments.filter((s) => s.flag !== "normal").map((s) => (
                <li key={s.name}><span className={s.flag === "weak" ? "text-red-600" : "text-emerald-600"}>{s.flag}</span> · {s.name} ({s.rating}★)</li>
              ))}
            </ul>
          </div>
        </div>
      </Section>

      {/* 5 evidence */}
      <Section id="evidence" eyebrow="Evidence" title="Matched case studies & research">
        <div className="grid gap-4 md:grid-cols-3">
          {r.top_cases.map((tc) => (
            <div key={tc.id} className="card-white">
              <div className="flex items-center justify-between"><span className="chip">Case study ↗</span><span className="text-sm font-semibold text-brand">{tc.score.toFixed(2)}</span></div>
              <h3 className="mt-3 text-lg font-bold">{tc.id} · {tc.name}</h3>
              <p className="mt-2 text-[13px] text-ink/70">{tc.measured_roi_text}</p>
              <ul className="mt-3 space-y-1 text-[13px]">
                {Object.entries(tc.kpi_deltas).slice(0, 4).map(([k, v]) => (
                  <li key={k} className="flex justify-between gap-2"><span className="truncate text-ink/60">{k}</span><b>{pct(v)}</b></li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {r.top_snippets.map((s) => (
            <div key={s.id} className="card py-4"><p className="text-[13px] font-semibold text-brand">{s.id} · {s.source}</p><p className="mt-1 text-[14px]">{s.finding}</p></div>
          ))}
        </div>
      </Section>

      {/* 6 jury */}
      <Section eyebrow="Jury" title="What each stakeholder thinks">
        <div className="card">
          <ul className="divide-y divide-slate-200">
            {win.votes.map(([persona, v]) => (
              <li key={persona} className="grid gap-1 py-3 sm:grid-cols-[220px_80px_1fr]">
                <b>{persona}</b>
                <span className="font-semibold text-brand">{((v.feasibility + v.impact + (11 - v.risk)) / 3).toFixed(1)}/10</span>
                <span className="text-[14px] text-ink/70">{v.concern} <i className="text-ink/50">— {v.verdict}</i></span>
              </li>
            ))}
            {!win.votes.length && <li className="text-ink/50">No jury votes.</li>}
          </ul>
        </div>
      </Section>

      {/* 7 ROI */}
      <Section id="roi" eyebrow="ROI calculator" title="Return on the winning plan">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {[["Cost", eur(r.roi.cost_eur)], ["Expected benefit / yr", eur(r.roi.benefit_expected_eur)],
            ["Conservative / yr", eur(r.roi.benefit_conservative_eur)],
            ["ROI (exp. / cons.)", `${pct(r.roi.roi_expected)} / ${pct(r.roi.roi_conservative)}`],
            ["Payback", r.roi.payback_months_expected == null ? "–" : `${r.roi.payback_months_expected.toFixed(1)} mo`]].map(([k, v]) => (
            <div key={k} className="card-white p-5"><p className="text-xs font-semibold uppercase tracking-wider text-ink/50">{k}</p><p className="mt-2 font-display text-2xl font-extrabold">{v}</p></div>
          ))}
        </div>
        <div className="card mt-4 overflow-x-auto">
          <table className="w-full text-left text-[14px]">
            <thead className="text-xs uppercase tracking-wider text-ink/50"><tr><th className="pb-2">Line</th><th>Base</th><th>Δ exp.</th><th>Expected</th><th>Conservative</th><th>Precedents</th><th>Formula</th></tr></thead>
            <tbody>
              {r.roi.lines.map((l) => (
                <tr key={l.name} className={`border-t border-slate-200 ${l.applies ? "" : "text-ink/40"}`}>
                  <td className="py-2 font-semibold">{l.name.replace("_", " ")}</td>
                  <td>{l.base_value == null ? "–" : eur(l.base_value)}</td><td>{pct(l.expected_change)}</td>
                  <td>{eur(l.benefit_expected_eur)}</td><td>{eur(l.benefit_conservative_eur)}</td>
                  <td>{l.precedent_case_ids.join(", ") || "–"}</td><td className="text-[12px]">{l.formula}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-3 text-[12px] text-ink/50">Costs are placeholder assumptions (data/assumptions.json). Benefits come from precedent telemetry; no number is LLM-generated.</p>
        </div>
      </Section>

      {/* 8 charts */}
      <Section id="charts" eyebrow="Analytics" title="Under the hood">
        <Charts r={r} />
      </Section>

      {/* 9 alternatives */}
      <Section eyebrow="Alternatives" title="Runner-up strategies">
        <div className="space-y-3">
          {r.ranked.slice(1).map((sp, i) => (
            <div key={sp.plan.plan_id} className="card p-0">
              <button className="flex w-full items-center justify-between px-6 py-4 text-left" onClick={() => setOpenAlt(openAlt === sp.plan.plan_id ? null : sp.plan.plan_id)}>
                <span><span className="eyebrow mr-3">#{i + 2}</span><b className="font-display text-lg">{sp.plan.title}</b></span>
                <span className="text-sm text-ink/60">final {sp.final?.toFixed(2)} {openAlt === sp.plan.plan_id ? "▾" : "▸"}</span>
              </button>
              {openAlt === sp.plan.plan_id && (
                <div className="border-t border-slate-200 p-6"><p className="mb-4 text-ink/80">{sp.plan.thesis}</p><PlanPhases sp={sp} r={r} compact /></div>
              )}
            </div>
          ))}
        </div>
      </Section>

      {/* 10 trace */}
      <section className="flex flex-wrap gap-3">
        <button className="btn-ghost" onClick={() => setShowTrace(!showTrace)}>{showTrace ? "Hide" : "Show"} raw trace</button>
        <button className="btn-ghost" onClick={download}>Download run JSON</button>
        {showTrace && (
          <pre className="mt-2 max-h-[480px] w-full overflow-auto rounded-2xl bg-ink p-5 text-[12px] text-slate-100">
            {JSON.stringify({ trace: r.trace, decisions: win.decisions, leadership: r.leadership_decisions }, null, 2)}
          </pre>
        )}
      </section>
    </div>
  );
}
