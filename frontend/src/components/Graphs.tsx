import { useState, type ReactNode } from "react";
import { Bar, BarChart, CartesianGrid, Cell, LabelList, Line, LineChart, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ResultV2 } from "../typesV2";

/** Chart roles (validated with the dataviz palette validator against the white card surface: all checks pass). */
const C = {
  expected: "#2a78d6",      // series slot 1 (blue)
  conservative: "#eb6834",  // series slot 2 (orange)
  worse: "#e34948",         // diverging warm pole
  better: "#2a78d6",        // diverging cool pole
  chosen: "#2a78d6",        // highlighted entity
  other: "#c3c2b7",         // de-emphasised entities
  grid: "#e1e0d9", axis: "#c3c2b7", muted: "#898781", ink: "#1e1b4b", inkSoft: "#52514e",
};
const eur = (v: number) => "€" + Math.round(v).toLocaleString("en-US");
const eurShort = (v: number) => (Math.abs(v) >= 1e6 ? `€${(v / 1e6).toFixed(1)}M` : Math.abs(v) >= 1e3 ? `€${Math.round(v / 1e3)}K` : `€${Math.round(v)}`);
const tick = { fill: C.muted, fontSize: 11 };

function ChartCard({ title, subtitle, legend, table, note, children }:
  { title: string; subtitle: string; legend?: { color: string; label: string }[]; table: { cols: string[]; rows: (string | number)[][] }; note?: string; children: ReactNode }) {
  const [asTable, setAsTable] = useState(false);
  return (
    <figure className="card-white min-w-0">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <figcaption className="text-[16px] font-bold">{title}</figcaption>
          <p className="text-[13px] text-ink/60">{subtitle}</p>
        </div>
        <button onClick={() => setAsTable(!asTable)} className="rounded-full border border-slate-200 px-2.5 py-0.5 text-[12px] font-semibold text-ink/60 hover:border-brand hover:text-brand">
          {asTable ? "Show as chart" : "Show as table"}
        </button>
      </div>
      {legend && legend.length > 1 && !asTable && (
        <div className="mt-3 flex flex-wrap gap-4 text-[12px] text-ink/70">
          {legend.map((l) => <span key={l.label} className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: l.color }} />{l.label}</span>)}
        </div>
      )}
      <div className="mt-3">
        {asTable ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[13px]" style={{ fontVariantNumeric: "tabular-nums" }}>
              <thead className="text-[11px] uppercase tracking-wider text-ink/50"><tr>{table.cols.map((c) => <th key={c} className="py-1.5 pr-4">{c}</th>)}</tr></thead>
              <tbody>{table.rows.map((row, i) => <tr key={i} className="border-t border-slate-200">{row.map((v, j) => <td key={j} className="py-1.5 pr-4">{v}</td>)}</tr>)}</tbody>
            </table>
          </div>
        ) : children}
      </div>
      {note && <p className="mt-2 text-[12px] text-ink/50">{note}</p>}
    </figure>
  );
}

function Tip({ active, payload, label, render }: { active?: boolean; payload?: { payload: Record<string, unknown> }[]; label?: unknown; render: (p: Record<string, unknown>, label: unknown) => ReactNode }) {
  if (!active || !payload?.length) return null;
  return <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-[12px] shadow-md">{render(payload[0].payload, label)}</div>;
}

// ---------- 1 payback curve ----------
export function PaybackChart({ r }: { r: ResultV2 }) {
  const { cost_eur: cost, benefit_expected_eur: exp, benefit_conservative_eur: cons, payback_months_expected: pb } = r.roi;
  if (!exp) return null;
  const consPb = cons > 0 ? cost / (cons / 12) : null;
  const months = Math.max(12, Math.min(36, Math.ceil(Math.max(pb ?? 12, consPb ?? 0, 12) * 1.25)));
  const data = Array.from({ length: months + 1 }, (_, m) => ({ m, expected: (exp / 12) * m, conservative: (cons / 12) * m }));
  return (
    <ChartCard title="When the plan pays for itself" subtitle={`Benefit building up month by month against the one-off cost of ${eur(cost)}.`}
      legend={[{ color: C.expected, label: "Expected benefit" }, { color: C.conservative, label: "Conservative benefit" }]}
      note="Assumes benefits build up evenly from the first month, as in the payback figure. The grey line is the cost; each dot marks where a benefit line repays it."
      table={{ cols: ["Month", "Expected (cumulative)", "Conservative (cumulative)", "Cost"],
               rows: data.filter((d) => d.m % 3 === 0).map((d) => [d.m, eur(d.expected), eur(d.conservative), eur(cost)]) }}>
      <div className="h-[260px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 16, right: 24, bottom: 18, left: 8 }}>
            <CartesianGrid vertical={false} stroke={C.grid} />
            <XAxis dataKey="m" type="number" domain={[0, months]} allowDecimals={false} tickCount={Math.min(13, months + 1)}
              tick={tick} tickLine={false} axisLine={{ stroke: C.axis }}
              label={{ value: "months from start", position: "insideBottom", offset: -10, fill: C.muted, fontSize: 11 }} />
            <YAxis tickFormatter={eurShort} tick={tick} tickLine={false} axisLine={false} width={56} />
            <Tooltip cursor={{ stroke: C.axis }} content={<Tip render={(p) => (<>
              <p className="font-semibold">Month {String(p.m)}</p>
              <p><span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: C.expected }} />Expected: {eur(p.expected as number)}</p>
              <p><span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: C.conservative }} />Conservative: {eur(p.conservative as number)}</p>
              <p className="text-ink/60">Cost: {eur(cost)}</p></>)} />} />
            <ReferenceLine y={cost} stroke={C.muted} strokeWidth={1} label={{ value: `Cost ${eurShort(cost)}`, position: "insideTopLeft", fill: C.inkSoft, fontSize: 11 }} />
            <Line isAnimationActive={false} type="linear" dataKey="expected" stroke={C.expected} strokeWidth={2} dot={false} activeDot={{ r: 5, stroke: "#fff", strokeWidth: 2 }} />
            <Line isAnimationActive={false} type="linear" dataKey="conservative" stroke={C.conservative} strokeWidth={2} dot={false} activeDot={{ r: 5, stroke: "#fff", strokeWidth: 2 }} />
            {pb != null && pb <= months && (
              <ReferenceDot x={Math.round(pb * 10) / 10} y={cost} r={5} fill={C.expected} stroke="#fff" strokeWidth={2}
                label={{ value: `expected payback: ${pb.toFixed(1)} months`, position: "top", offset: 12, fill: C.ink, fontSize: 12, fontWeight: 600 }} />
            )}
            {consPb != null && consPb <= months && (
              <ReferenceDot x={Math.round(consPb * 10) / 10} y={cost} r={5} fill={C.conservative} stroke="#fff" strokeWidth={2}
                label={{ value: `conservative: ${consPb.toFixed(1)} months`, position: "bottom", offset: 12, fill: C.inkSoft, fontSize: 11 }} />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}

// ---------- 2 where the benefit comes from ----------
const LINE_NAME: Record<string, string> = {
  attrition_exposure: "Lower staff-turnover cost", agency_spend: "Less agency spend",
  hr_hours: "HR hours freed", emv: "Free media reach (EMV)",
};

export function BenefitSources({ r }: { r: ResultV2 }) {
  const rows = r.roi.lines.filter((l) => l.applies && l.benefit_expected_eur > 0)
    .map((l) => ({ name: LINE_NAME[l.name] ?? l.name, expected: l.benefit_expected_eur, conservative: l.benefit_conservative_eur, formula: l.formula, cases: l.precedent_case_ids.join(", ") }))
    .sort((a, b) => b.expected - a.expected);
  if (!rows.length) return null;
  return (
    <ChartCard title="Where the yearly benefit comes from" subtitle="Each source of value, expected and conservative, per year."
      legend={[{ color: C.expected, label: "Expected per year" }, { color: C.conservative, label: "Conservative per year" }]}
      table={{ cols: ["Source", "Expected / year", "Conservative / year", "Based on"], rows: rows.map((x) => [x.name, eur(x.expected), eur(x.conservative), x.cases]) }}>
      <div style={{ height: rows.length * 64 + 40 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 64, bottom: 4, left: 8 }} barGap={2} barCategoryGap="22%">
            <CartesianGrid horizontal={false} stroke={C.grid} />
            <XAxis type="number" tickFormatter={eurShort} tick={tick} tickLine={false} axisLine={{ stroke: C.axis }} />
            <YAxis type="category" dataKey="name" width={150} tick={{ fill: C.inkSoft, fontSize: 12 }} tickLine={false} axisLine={false} />
            <Tooltip cursor={{ fill: "rgba(30,27,75,0.04)" }} content={<Tip render={(p) => (<>
              <p className="font-semibold">{String(p.name)}</p>
              <p>Expected: {eur(p.expected as number)} per year</p><p>Conservative: {eur(p.conservative as number)} per year</p>
              <p className="max-w-[260px] text-ink/60">{String(p.formula)}</p></>)} />} />
            <Bar isAnimationActive={false} dataKey="expected" fill={C.expected} radius={[0, 4, 4, 0]} barSize={12}>
              <LabelList dataKey="expected" position="right" formatter={(v: number) => eurShort(v)} style={{ fill: C.inkSoft, fontSize: 11 }} />
            </Bar>
            <Bar isAnimationActive={false} dataKey="conservative" fill={C.conservative} radius={[0, 4, 4, 0]} barSize={12} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}

// ---------- 3 company vs sector average ----------
export function GapChart({ r }: { r: ResultV2 }) {
  const accepted = new Set(r.confidence.map((c) => c.problem));
  const role = Object.fromEntries(r.roots.causes.map((c) => [c.problem, c.role]));
  const ROLE: Record<string, string> = { root: "root cause", standalone: "standalone problem", intermediate: "in between", symptom: "symptom" };
  const rows = r.problems.flatMap((p) => {
    const pool = accepted.has(p.problem) ? p.measured : p.status === "healthy" ? p.healthy : [];
    const ms = pool.filter((m) => m.peer != null && m.gap_pct != null);
    if (!ms.length) return [];
    const m = accepted.has(p.problem) ? ms.reduce((a, b) => ((b.gap_pct ?? 0) > (a.gap_pct ?? 0) ? b : a))
      : ms.reduce((a, b) => ((b.gap_pct ?? 0) < (a.gap_pct ?? 0) ? b : a));
    const g = (m.gap_pct ?? 0) * 100;
    return [{ name: p.label, gap: Math.max(-100, Math.min(100, g)), real: g, metric: m.label, value: m.value, peer: m.peer,
              kind: accepted.has(p.problem) ? ROLE[role[p.problem]] ?? "problem" : "strength to protect" }];
  }).sort((a, b) => b.real - a.real);
  if (!rows.length) return null;
  const fmt = (v: number) => `${v > 0 ? "+" : "−"}${Math.abs(Math.round(v))}%`;
  return (
    <ChartCard title="The company against the sector average" subtitle="For each problem (and each strength), its clearest metric: how far it is from similar companies."
      legend={[{ color: C.worse, label: "Worse than the sector average" }, { color: C.better, label: "Better than the sector average" }]}
      note="Bars stop at ±100%; the label shows the real gap. 'Worse' already accounts for metrics where lower is better."
      table={{ cols: ["Problem / strength", "Role", "Metric", "Company", "Sector", "Gap"], rows: rows.map((x) => [x.name, x.kind, x.metric, x.value, x.peer ?? "–", fmt(x.real)]) }}>
      <div style={{ height: rows.length * 30 + 40 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 56, bottom: 4, left: 8 }}>
            <CartesianGrid horizontal={false} stroke={C.grid} />
            <XAxis type="number" domain={[-100, 100]} ticks={[-100, -50, 0, 50, 100]} tickFormatter={(v) => (v === 0 ? "0" : fmt(v))} tick={tick} tickLine={false} axisLine={{ stroke: C.axis }} />
            <YAxis type="category" dataKey="name" width={190} tick={{ fill: C.inkSoft, fontSize: 12 }} tickLine={false} axisLine={false} />
            <ReferenceLine x={0} stroke={C.axis} />
            <Tooltip cursor={{ fill: "rgba(30,27,75,0.04)" }} content={<Tip render={(p) => (<>
              <p className="font-semibold">{String(p.name)} <span className="font-normal text-ink/60">({String(p.kind)})</span></p>
              <p>{String(p.metric)}: {String(p.value)} vs sector {String(p.peer)}</p>
              <p>{fmt(p.real as number)} {(p.real as number) > 0 ? "worse" : "better"} than similar companies</p></>)} />} />
            <Bar isAnimationActive={false} dataKey="gap" barSize={14} radius={4}>
              {rows.map((x, i) => <Cell key={i} fill={x.real > 0 ? C.worse : C.better} />)}
              <LabelList dataKey="real" content={(props) => {
                const { x = 0, y = 0, width = 0, height = 0, value } = props as { x?: number; y?: number; width?: number; height?: number; value?: number };
                const v = Number(value), end = Number(x) + Number(width);
                return <text x={v >= 0 ? end + 6 : end - 6} y={Number(y) + Number(height) / 2 + 4} textAnchor={v >= 0 ? "start" : "end"} fill={C.inkSoft} fontSize={11}>{fmt(v)}</text>;
              }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}

// ---------- 4 why this plan won (small multiples, one scale each) ----------
export function PlanComparison({ r }: { r: ResultV2 }) {
  const plans = [...r.plans].sort((a, b) => (b.final ?? 0) - (a.final ?? 0));
  if (plans.length < 2) return null;
  const name = (p: typeof plans[number]) => `${p.plan_id} · ${p.variant}`;
  const metrics: { key: string; title: string; get: (p: typeof plans[number]) => number | null; fmt: (v: number) => string; max?: number; note: string }[] = [
    { key: "final", title: "Overall score", get: (p) => p.final, fmt: (v) => v.toFixed(2), max: 1, note: "half audited jury, half engine checks" },
    { key: "coverage", title: "Root causes covered", get: (p) => p.coverage, fmt: (v) => `${Math.round(v * 100)}%`, max: 1, note: "weighted by importance" },
    { key: "evidence", title: "Actions backed by evidence", get: (p) => p.evidence_strength, fmt: (v) => `${Math.round(v * 100)}%`, max: 1, note: "share with a precedent or research" },
    { key: "jury", title: "Jury score", get: (p) => p.jury_score, fmt: (v) => v.toFixed(2), max: 1, note: "after the jury critic's audit" },
    { key: "cost", title: "Cost", get: (p) => p.cost_eur, fmt: eurShort, note: "lower is cheaper" },
  ];
  return (
    <ChartCard title="Why this plan was chosen" subtitle="The recommended plan against the alternatives, one measure per panel (each with its own scale)."
      legend={[{ color: C.chosen, label: "Recommended plan" }, { color: C.other, label: "Alternatives" }]}
      table={{ cols: ["Plan", ...metrics.map((m) => m.title)], rows: plans.map((p) => [`${name(p)}${p.plan_id === r.winner ? " (chosen)" : ""}`, ...metrics.map((m) => { const v = m.get(p); return v == null ? "–" : m.fmt(v); })]) }}>
      <div className="grid gap-x-8 gap-y-5 sm:grid-cols-2 xl:grid-cols-3">
        {metrics.map((m) => {
          const vals = plans.map((p) => m.get(p) ?? 0);
          const max = m.max ?? Math.max(...vals, 1);
          return (
            <div key={m.key}>
              <p className="text-[13px] font-semibold">{m.title}</p>
              <p className="mb-2 text-[11px] text-ink/50">{m.note}</p>
              <ul className="space-y-1.5">
                {plans.map((p) => {
                  const v = m.get(p);
                  const chosen = p.plan_id === r.winner;
                  return (
                    <li key={p.plan_id} className="grid grid-cols-[84px_1fr_48px] items-center gap-2 text-[12px]" title={`${p.title}: ${v == null ? "no score" : m.fmt(v)}`}>
                      <span className={`truncate ${chosen ? "font-semibold text-ink" : "text-ink/60"}`}>{name(p)}</span>
                      <span className="h-3 rounded-r" style={{ width: `${v == null ? 0 : Math.max(2, (v / max) * 100)}%`, background: chosen ? C.chosen : C.other, borderTopRightRadius: 4, borderBottomRightRadius: 4 }} />
                      <span className="text-right text-ink/70" style={{ fontVariantNumeric: "tabular-nums" }}>{v == null ? "–" : m.fmt(v)}</span>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </div>
    </ChartCard>
  );
}
