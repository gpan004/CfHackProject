import { Bar, BarChart, CartesianGrid, Cell, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { PipelineResult } from "../types";

const BRAND = "#4f46e5";
const PALETTE = ["#4f46e5", "#1e1b4b", "#a5b4fc", "#f59e0b", "#10b981"];

function Heatmap({ rows, cols, values }: { rows: string[]; cols: string[]; values: number[][] }) {
  return (
    <div className="overflow-x-auto">
      <div className="grid gap-1 text-[11px]" style={{ gridTemplateColumns: `56px repeat(${cols.length}, minmax(44px, 1fr))` }}>
        <div />
        {cols.map((c) => <div key={c} className="truncate text-center font-semibold text-ink/60" title={c}>{c}</div>)}
        {rows.map((r, i) => [
          <div key={r} className="flex items-center font-semibold text-ink/60">{r}</div>,
          ...cols.map((c, j) => {
            const v = values[i]?.[j] ?? 0;
            return (
              <div key={r + c} className="flex h-10 items-center justify-center rounded-md border border-slate-200"
                style={{ background: `rgba(79,70,229,${Math.min(1, Math.max(0, v))})`, color: v > 0.5 ? "#fff" : "#1e1b4b" }}>
                {v.toFixed(2)}
              </div>
            );
          }),
        ])}
      </div>
    </div>
  );
}

function Panel({ title, sub, children }: { title: string; sub: string; children: React.ReactNode }) {
  return (
    <div className="card-white">
      <h3 className="text-lg font-bold">{title}</h3>
      <p className="mb-4 text-[13px] text-ink/60">{sub}</p>
      {children}
    </div>
  );
}

export default function Charts({ r }: { r: PipelineResult }) {
  const relation = r.root_causes.map((x) => ({ id: x.hypothesis.id, relation: +x.relation.toFixed(3) }));
  const topIds = r.top_cases.map((c) => c.id);
  const al = r.case_alignment;
  const alValues = al.values.map((row) => topIds.map((id) => row[al.col_ids.indexOf(id)] ?? 0));

  const plans = r.ranked.map((sp) => sp.plan.plan_id);
  const personas = Array.from(new Set(r.ranked.flatMap((sp) => sp.votes.map(([p]) => p))));
  const jury = plans.map((pid) => {
    const sp = r.ranked.find((s) => s.plan.plan_id === pid)!;
    const row: Record<string, number | string> = { plan: pid };
    sp.votes.forEach(([p, v]) => (row[p] = +((v.feasibility + v.impact + (11 - v.risk)) / 3).toFixed(2)));
    return row;
  });
  const kpis = r.kpis.map((k) => ({ key: k.key.replace(/_/g, " "), t0: k.t0, peer: k.peer, projected: k.projected == null ? null : +k.projected.toFixed(2) }));
  const axis = { fontSize: 11, fill: "#475569" };

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Panel title="Causal influence matrix" sub="DEMATEL input: row causes column (0–1). Relation > 0 = root cause.">
        <Heatmap rows={r.influence_ids} cols={r.influence_ids} values={r.influence_matrix} />
        <div className="mt-4 h-44">
          <ResponsiveContainer>
            <BarChart data={relation}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="id" tick={axis} /><YAxis tick={axis} /><Tooltip />
              <Bar dataKey="relation" radius={[4, 4, 0, 0]}>
                {relation.map((d) => <Cell key={d.id} fill={d.relation > 0 ? BRAND : "#cbd5e1"} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Panel>
      <Panel title="Case alignment" sub="Root causes × top case studies (semantic + concept + LLM, sector-fit gated).">
        <Heatmap rows={al.row_ids} cols={topIds} values={alValues} />
      </Panel>
      <Panel title="Jury scores" sub="Persona score per plan: (feasibility + impact + 11 − risk) / 3.">
        <div className="h-72">
          <ResponsiveContainer>
            <BarChart data={jury}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="plan" tick={axis} /><YAxis domain={[0, 10]} tick={axis} /><Tooltip /><Legend wrapperStyle={{ fontSize: 11 }} />
              {personas.map((p, i) => <Bar key={p} dataKey={p} fill={PALETTE[i % PALETTE.length]} radius={[3, 3, 0, 0]} />)}
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Panel>
      <Panel title="KPI projection" sub="Precedent-based 12-month projection vs today and sector peers.">
        <div className="h-72">
          <ResponsiveContainer>
            <BarChart data={kpis}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="key" tick={{ ...axis, fontSize: 9 }} interval={0} /><YAxis tick={axis} /><Tooltip /><Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey="t0" name="today" fill="#1e1b4b" radius={[3, 3, 0, 0]} />
              <Bar dataKey="peer" name="peer" fill="#cbd5e1" radius={[3, 3, 0, 0]} />
              <Bar dataKey="projected" name="projected" fill={BRAND} radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Panel>
    </div>
  );
}
