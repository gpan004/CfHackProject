import { useEffect, useState } from "react";
import type { RunState, ScenarioInfo } from "../types";
import { NEUTRAL, type Audience, type Focus } from "../typesV2";
import { AudiencePicker, FocusSwitches } from "./Tailor";

const STAGES_V1 = ["ingest", "pillar_analysis", "hypotheses", "confutation", "causal_map", "matching",
  "strategy", "guardrails", "jury", "ranking", "metrics"];
const STAGES_V2 = ["intake", "measure", "diagnose", "challenge", "root_causes", "precedents", "gates", "strategy",
  "critic", "plans", "jury", "jury_critic", "stability", "report"];
const KIND_V2: Record<string, string> = { diagnose: "agent", challenge: "agent", strategy: "agent", jury: "agent", report: "agent",
  critic: "critic", jury_critic: "critic" };
const UNSEEN = "__unseen__";
export type Engine = "v1" | "v2";

interface Props {
  scenarios: ScenarioInfo[]; run: { stage: string | null; status: string; stages_done: string[] } | RunState | null;
  busy: boolean; onRun: (body: object) => void; engine: Engine; setEngine: (e: Engine) => void;
}

export default function RunPanel({ scenarios, run, busy, onRun, engine, setEngine }: Props) {
  const STAGES = engine === "v2" ? STAGES_V2 : STAGES_V1;
  const [code, setCode] = useState("");
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [focus, setFocus] = useState<Focus>(NEUTRAL);
  const [audience, setAudience] = useState<Audience>("board");
  const [tailorOpen, setTailorOpen] = useState(true);
  const extra = engine === "v2" ? { focus, audience } : {};

  useEffect(() => { if (!code && scenarios.length) setCode(scenarios[0].scenario_code); }, [scenarios, code]);

  const submit = () => {
    setJsonError(null);
    let parsed: any = undefined;
    if (text.trim()) {
      try { parsed = JSON.parse(text); } catch (e) { setJsonError(String(e)); return; }
    }
    if (code === UNSEEN) {
      if (!parsed?.scenario) { setJsonError('Paste {"scenario": {...}, "snapshot": {...optional}}'); return; }
      onRun({ scenario: parsed.scenario, snapshot: parsed.snapshot, ...extra });
    } else {
      onRun({ scenario_code: code, overrides: parsed, ...extra });
    }
  };

  return (
    <div className="card-white">
      <p className="eyebrow">Intake</p>
      <h2 className="mt-2 text-xl font-bold">Run the engine</h2>

      <div className="mt-4 grid grid-cols-2 gap-1 rounded-btn border border-slate-200 bg-slate-50 p-1 text-[13px] font-semibold">
        {(["v2", "v1"] as Engine[]).map((e) => (
          <button key={e} disabled={busy} onClick={() => setEngine(e)}
            className={`rounded-lg px-2 py-2 ${engine === e ? "bg-white text-brand shadow" : "text-ink/60"}`}>
            {e === "v2" ? "Evidence engine (v2)" : "Classic (v1)"}
          </button>
        ))}
      </div>
      <p className="mt-2 text-[12px] text-ink/50">
        {engine === "v2" ? "Knowledge-graph tools decide; agents explain; critics check. Same data, same answer."
          : "The original pipeline, kept as the fallback."}
      </p>

      <label className="mt-5 block text-sm font-medium">Company scenario</label>
      <select value={code} onChange={(e) => setCode(e.target.value)}
        className="mt-1.5 w-full rounded-btn border border-slate-200 bg-white px-3 py-2.5 text-[15px] outline-none focus:border-brand">
        {scenarios.map((s) => <option key={s.scenario_code} value={s.scenario_code}>{s.company_name} · {s.industry}</option>)}
        <option value={UNSEEN}>Unseen company (paste JSON)</option>
      </select>

      <button onClick={() => setOpen(!open)} className="mt-4 text-sm font-semibold text-brand">
        {open ? "▾" : "▸"} {code === UNSEEN ? "Company JSON" : "Edit intake (JSON overrides)"}
      </button>
      {(open || code === UNSEEN) && (
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={8} spellCheck={false}
          placeholder={code === UNSEEN ? '{"scenario": {...}, "snapshot": {...}}'
            : '{"snapshot": {"t0_current_snapshot": {"public_reputation": {"external_claims_gap_stars_5": 0.3}}}}'}
          className="mt-2 w-full rounded-xl border border-slate-200 bg-slate-50 p-3 font-mono text-xs outline-none focus:border-brand" />
      )}
      {jsonError && <p className="mt-1 text-xs text-red-600">{jsonError}</p>}

      {engine === "v2" && (
        <div className="mt-5 border-t border-slate-200 pt-4">
          <button onClick={() => setTailorOpen(!tailorOpen)} className="flex w-full items-center justify-between text-left">
            <span className="text-sm font-semibold">Tailor this analysis</span><span className="text-brand">{tailorOpen ? "▾" : "▸"}</span>
          </button>
          {tailorOpen && (
            <div className="mt-3 space-y-4">
              <div><p className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink/50">Priorities</p>
                <FocusSwitches focus={focus} onChange={setFocus} disabled={busy} /></div>
              <div><p className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink/50">Who will read it</p>
                <AudiencePicker value={audience} onChange={setAudience} disabled={busy} /></div>
            </div>
          )}
        </div>
      )}

      <button className="btn mt-5 w-full" disabled={busy || !code} onClick={submit}>
        {busy ? "Running…" : "Run analysis"}
      </button>

      {run && (
        <ol className="mt-6 space-y-2 border-t border-slate-200 pt-5 text-sm">
          {STAGES.map((s, i) => {
            const done = run.stages_done.includes(s);
            const active = run.stage === s && run.status === "running" && !done;
            return (
              <li key={s} className="flex items-center gap-3">
                <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold
                  ${done ? "bg-brand text-white" : active ? "border-2 border-brand" : "border border-slate-300 text-slate-400"}`}>
                  {done ? "✓" : active ? <span className="h-3 w-3 animate-spin rounded-full border-2 border-brand border-t-transparent" /> : i + 1}
                </span>
                <span className={done || active ? "text-ink" : "text-slate-400"}>{s.replace("_", " ")}</span>
                {engine === "v2" && KIND_V2[s] && <span className="ml-auto rounded bg-slate-100 px-1.5 text-[10px] uppercase text-ink/50">{KIND_V2[s]}</span>}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
