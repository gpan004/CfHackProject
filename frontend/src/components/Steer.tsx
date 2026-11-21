import { useEffect, useRef, useState } from "react";
import { checkRequestV2, whatIfV2 } from "../api";
import { NEUTRAL, PILLARS, type Focus, type RequestCheck, type ResultV2, type WhatIfResult } from "../typesV2";
import { FocusSwitches } from "./Tailor";

const eur = (v: number) => "€" + Math.round(v).toLocaleString("en-US");
const VERDICT_TONE: Record<string, string> = {
  yes_now: "border-emerald-200 bg-emerald-50 text-emerald-800", already_planned: "border-emerald-200 bg-emerald-50 text-emerald-800",
  later: "border-amber-200 bg-amber-50 text-amber-800", no: "border-red-200 bg-red-50 text-red-700",
};
const EXAMPLES = ["Let's launch employee ambassadors now", "Can we do a salary review?", "Rewrite our job ads tomorrow", "Start a LinkedIn blog series"];

function focusFrom(r: ResultV2): Focus {
  const f = { ...NEUTRAL };
  PILLARS.forEach((p) => { const v = r.focus?.requested?.[p.id]; if (v === "less" || v === "more" || v === "normal") f[p.id] = v; });
  return f;
}

/** Instant what-if (no AI): priorities vs the neutral analysis, and what stays fixed. */
function WhatIf({ r, onRerun }: { r: ResultV2; onRerun: (f: Focus) => void }) {
  const [focus, setFocus] = useState<Focus>(focusFrom(r));
  const [res, setRes] = useState<WhatIfResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const seq = useRef(0);
  const lab = (id: string) => r.labels[id] ?? id;

  useEffect(() => {
    const n = ++seq.current;
    whatIfV2({ ...r.request, focus, problems: r.confidence.map((c) => c.problem) })
      .then((x) => { if (n === seq.current) { setRes(x); setErr(null); } })
      .catch((e) => setErr(String(e)));
  }, [focus, r]);

  const changed = JSON.stringify(focus) !== JSON.stringify(focusFrom(r));
  return (
    <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
      <div className="card">
        <p className="font-semibold">Your priorities</p>
        <p className="mb-3 text-[12px] text-ink/60">Change a switch: the comparison updates instantly. No AI is involved.</p>
        <FocusSwitches focus={focus} onChange={setFocus} />
        <button className="btn mt-4 w-full px-4 py-2.5 text-[14px]" disabled={!changed} onClick={() => onRerun(focus)}>
          Run the full analysis with these priorities
        </button>
        <p className="mt-1 text-[11px] text-ink/50">The full run re-checks everything with the agents and critics (several minutes).</p>
      </div>
      <div className="card-white min-w-0">
        {err && <p className="text-sm text-red-700">{err}</p>}
        {!res ? <p className="text-ink/50">Calculating…</p> : (
          <div className="space-y-4">
            {res.focus.warnings.map((w, i) => <p key={i} className="rounded-lg border border-amber-300 bg-amber-50 p-2.5 text-[13px] text-amber-800">⚠ {w}</p>)}
            <ul className="space-y-1 text-[14px]">{res.summary.map((s, i) => <li key={i}>• {s}</li>)}</ul>
            <div className="grid gap-3 sm:grid-cols-3">
              {[["Cost", res.roi_before.cost_eur, res.roi_after.cost_eur], ["Benefit / year", res.roi_before.benefit_expected_eur, res.roi_after.benefit_expected_eur],
                ["Payback (months)", res.roi_before.payback_months_expected, res.roi_after.payback_months_expected]].map(([k, b, a]) => (
                <div key={k as string} className="rounded-xl border border-slate-200 p-3">
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-ink/50">{k as string}</p>
                  <p className="mt-1 text-[13px] text-ink/50">neutral: {b == null ? "–" : k === "Payback (months)" ? (b as number).toFixed(1) : eur(b as number)}</p>
                  <p className="font-display text-lg font-bold">{a == null ? "–" : k === "Payback (months)" ? (a as number).toFixed(1) : eur(a as number)}</p>
                </div>
              ))}
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-ink/50">Order of importance (root causes first)</p>
              <ol className="mt-2 space-y-1 text-[13px]">
                {res.priorities.filter((p) => p.role !== "symptom").slice(0, 8).map((p) => {
                  const delta = p.rank_before - p.rank_after;
                  return (
                    <li key={p.problem} className="flex items-center gap-2">
                      <span className="w-6 text-right font-semibold">{p.rank_after}.</span><span>{p.label}</span>
                      {delta !== 0 && <span className={`text-[11px] font-semibold ${delta > 0 ? "text-emerald-700" : "text-red-600"}`}>{delta > 0 ? `▲ ${delta}` : `▼ ${-delta}`}</span>}
                      {res.focus.deferred.includes(p.problem) && <span className="chip">deferred by you</span>}
                    </li>
                  );
                })}
              </ol>
            </div>
            {(res.diff.added.length > 0 || res.diff.removed.length > 0 || res.diff.moved.length > 0) && (
              <div className="text-[13px]">
                <p className="text-xs font-semibold uppercase tracking-wider text-ink/50">Plan changes vs neutral</p>
                {res.diff.added.map((a) => <p key={a} className="text-emerald-700">+ {lab(a)}</p>)}
                {res.diff.removed.map((a) => <p key={a} className="text-red-600">− {lab(a)}</p>)}
                {res.diff.moved.map((a) => <p key={a} className="text-amber-700">↔ {lab(a.split(":")[0])}{a.slice(a.indexOf(":"))}</p>)}
              </div>
            )}
            <details className="text-[12px] text-ink/70">
              <summary className="cursor-pointer font-semibold text-brand">Rules your priorities cannot change ({res.unchanged_rules.length})</summary>
              <ul className="mt-1 space-y-1">{res.unchanged_rules.map((u, i) => <li key={i}>• {u}</li>)}</ul>
            </details>
          </div>
        )}
      </div>
    </div>
  );
}

/** The client types a request; the engine answers from the rules and the evidence (no AI). */
function RequestChecker({ r }: { r: ResultV2 }) {
  const [text, setText] = useState("");
  const [res, setRes] = useState<RequestCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const win = r.plans.find((p) => p.plan_id === r.winner)!;
  const ask = async (t: string) => {
    if (!t.trim()) return;
    setText(t); setBusy(true); setErr(null);
    try {
      setRes(await checkRequestV2({ ...r.request, text: t, problems: r.confidence.map((c) => c.problem),
        plan: win.actions.filter((a) => !a.original).map((a) => ({ action: a.action, phase: a.phase })) }));
    } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  };
  return (
    <div className="card-white">
      <p className="font-semibold">Check a request</p>
      <p className="text-[12px] text-ink/60">Type what you are considering. The engine answers with the same rules as the plan, and shows why.</p>
      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ask(text)}
          placeholder="e.g. Let's launch employee ambassadors now"
          className="min-w-0 flex-1 rounded-btn border border-slate-200 px-3 py-2.5 text-[14px] outline-none focus:border-brand" />
        <button className="btn px-5 py-2.5 text-[14px]" disabled={busy || !text.trim()} onClick={() => ask(text)}>{busy ? "Checking…" : "Check"}</button>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {EXAMPLES.map((x) => <button key={x} onClick={() => ask(x)} className="rounded-full border border-slate-200 px-2.5 py-0.5 text-[12px] text-ink/60 hover:border-brand hover:text-brand">{x}</button>)}
      </div>
      {err && <p className="mt-3 text-sm text-red-700">{err}</p>}
      {res && (
        <div className="mt-4 space-y-3">
          {!res.understood && (
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-[13px]">
              <p>{res.note}</p>
              {res.suggestions.length > 0 && <div className="mt-2 flex flex-wrap gap-1.5">{res.suggestions.map((s) =>
                <button key={s.action} onClick={() => ask(s.label)} className="chip">{s.label}</button>)}</div>}
            </div>
          )}
          {res.matches.map((m) => (
            <div key={m.action} className={`rounded-xl border p-4 ${VERDICT_TONE[m.verdict]}`}>
              <p className="text-[12px] font-semibold uppercase tracking-wider opacity-70">{m.label}</p>
              <p className="mt-1 text-lg font-bold">{m.headline}</p>
              <p className="mt-1 text-[14px]">{m.reason}</p>
              <p className="mt-1 text-[13px] opacity-80">What it is: {m.plain}</p>
              {m.evidence.map((e, i) => <p key={i} className="mt-2 border-l-2 border-current pl-2 text-[12px] italic opacity-80">“{e.quote}” — {e.ref}</p>)}
              {m.precedents.length > 0 && <p className="mt-2 text-[12px] opacity-80">Used by similar companies: {m.precedents.map((c) => `${c} ${r.labels[c]?.split(" (")[0] ?? ""}`).join(", ")}</p>}
            </div>
          ))}
          {res.understood && <p className="text-[11px] text-ink/50">{res.note}</p>}
        </div>
      )}
    </div>
  );
}

export default function Steer({ r, onRerun }: { r: ResultV2; onRerun: (f: Focus) => void }) {
  return (
    <div className="space-y-4">
      <WhatIf r={r} onRerun={onRerun} />
      <RequestChecker r={r} />
    </div>
  );
}
