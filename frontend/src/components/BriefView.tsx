import { useEffect, useMemo, useState } from "react";
import { rewriteBriefV2 } from "../api";
import { downloadPdf } from "../pdf";
import { AUDIENCES, PILLARS, type Audience, type Brief, type CauseLink, type Focus, type MetricCheck, type PlanV2, type ResultV2, type ScheduledAction } from "../typesV2";
import Steer from "./Steer";

const eur = (v: number) => "€" + Math.round(v).toLocaleString("en-US");
const PHASE = ["", "First", "Second", "Third"];
const ROLE_TXT: Record<string, string> = { root: "Root cause", standalone: "Standalone problem", intermediate: "In between", symptom: "Symptom" };
const ROLE_TONE: Record<string, string> = {
  root: "border-red-300 bg-red-50 text-red-800", standalone: "border-orange-300 bg-orange-50 text-orange-800",
  intermediate: "border-amber-300 bg-amber-50 text-amber-800", symptom: "border-slate-300 bg-slate-50 text-slate-700",
};
const CONF_TONE = { high: "bg-emerald-100 text-emerald-800", medium: "bg-amber-100 text-amber-800", low: "bg-slate-200 text-slate-700" };

/** Hoverable source chip: shows the document title and text (cases, research, field notes). */
function Src({ id, r }: { id: string; r: ResultV2 }) {
  const d = r.documents[id];
  return (
    <span title={d ? `${d.title}\n\n${d.text}` : id}
      className="cursor-help rounded-md border border-brand/20 bg-brand-soft px-1.5 py-0.5 text-[11px] font-semibold text-brand">{id}</span>
  );
}

/** Renders text with [C05]-style citations turned into source chips. */
function Cited({ text, r }: { text: string; r: ResultV2 }) {
  const parts = text.split(/(\[[A-Z]{1,2}\d{1,2}\])/g);
  return <>{parts.map((p, i) => /^\[[A-Z]{1,2}\d{1,2}\]$/.test(p) ? <Src key={i} id={p.slice(1, -1)} r={r} /> : <span key={i}>{p}</span>)}</>;
}

function Term({ word, r }: { word: string; r: ResultV2 }) {
  const def = r.brief.glossary[word];
  return def ? <span title={def} className="cursor-help underline decoration-dotted underline-offset-4">{word}</span> : <>{word}</>;
}

function Section({ id, eyebrow, title, intro, children }: { id?: string; eyebrow: string; title: string; intro?: string; children: React.ReactNode }) {
  return (
    <section id={id} className="scroll-mt-28">
      <p className="eyebrow">{eyebrow}</p>
      <h2 className="section-title mt-2">{title}</h2>
      {intro && <p className="mt-2 max-w-3xl text-[15px] text-ink/70">{intro}</p>}
      <div className="mt-5">{children}</div>
    </section>
  );
}

/** Client vs sector peers, as two bars on the same scale. */
function MetricBar({ m }: { m: MetricCheck }) {
  const max = Math.max(m.value, m.peer ?? 0) || 1;
  const worse = (m.gap_pct ?? 0) > 0;
  return (
    <div className="text-[13px]">
      <div className="flex justify-between gap-2"><span className="text-ink/80">{m.label}</span>
        {m.gap_pct != null && <b className={worse ? "text-red-600" : "text-emerald-600"}>{Math.abs(m.gap_pct * 100).toFixed(0)}% {worse ? "worse" : "better"} than peers</b>}</div>
      <div className="mt-1 space-y-1">
        <div className="flex items-center gap-2"><span className="w-12 shrink-0 text-[11px] text-ink/50">Client</span>
          <div className="h-2.5 rounded-full bg-brand" style={{ width: `${(m.value / max) * 100}%` }} /><span className="text-[11px]">{m.value}</span></div>
        {m.peer != null && <div className="flex items-center gap-2"><span className="w-12 shrink-0 text-[11px] text-ink/50">Peers</span>
          <div className="h-2.5 rounded-full bg-slate-300" style={{ width: `${(m.peer / max) * 100}%` }} /><span className="text-[11px]">{m.peer}</span></div>}
      </div>
      {m.thresholds.map((t, i) => <p key={i} className="mt-1 text-[12px] text-red-700">⚠ {t}</p>)}
    </div>
  );
}

function ChainNode({ id, r, onPick, active }: { id: string; r: ResultV2; onPick: (id: string) => void; active: boolean }) {
  const c = r.roots.causes.find((x) => x.problem === id)!;
  const conf = r.confidence.find((x) => x.problem === id);
  return (
    <button onClick={() => onPick(id)} title={c.plain}
      className={`w-full rounded-xl border px-3 py-2 text-left text-[13px] transition ${ROLE_TONE[c.role]} ${active ? "ring-2 ring-brand" : ""}`}>
      <span className="font-semibold">{c.label}</span>
      {conf && <span className={`ml-2 rounded px-1.5 text-[10px] font-semibold uppercase ${CONF_TONE[conf.level]}`}>{conf.level}</span>}
    </button>
  );
}

/** Cause-and-effect chain in three columns; selecting a problem highlights its links and explains them. */
function Chain({ r }: { r: ResultV2 }) {
  const [pick, setPick] = useState<string | null>(null);
  const col = (roles: string[]) => r.roots.causes.filter((c) => roles.includes(c.role));
  const links = r.roots.links.filter((l) => !pick || l.source === pick || l.target === pick);
  const lab = (id: string) => r.labels[id] ?? id;
  return (
    <div className="card">
      <div className="grid gap-4 md:grid-cols-3">
        {[["Root causes (fix these)", ["root", "standalone"]], ["In between", ["intermediate"]], ["Symptoms (improve when causes are fixed)", ["symptom"]]].map(([t, roles]) => (
          <div key={t as string}>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink/50">{t as string}</p>
            <div className="space-y-2">
              {col(roles as string[]).map((c) => <ChainNode key={c.problem} id={c.problem} r={r} onPick={(x) => setPick(pick === x ? null : x)} active={pick === c.problem} />)}
              {!col(roles as string[]).length && <p className="text-[13px] text-ink/40">none</p>}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-5 border-t border-slate-200 pt-4">
        <p className="text-xs font-semibold uppercase tracking-wider text-ink/50">{pick ? `Links of “${lab(pick)}”` : "Why we think A causes B"} · click a problem to filter</p>
        <ul className="mt-2 space-y-2">
          {links.map((l: CauseLink, i) => (
            <li key={i} className="text-[14px]">
              <b>{lab(l.source)}</b> <span className="text-brand">→</span> <b>{lab(l.target)}</b>
              <span className="text-ink/70"> — {l.mechanism}</span>{" "}
              {l.origin === "client_text" ? <span className="chip">client's own words</span>
                : l.evidence.map((e) => <span key={e.ref + e.quote} className="mr-1"><Src id={e.ref} r={r} /></span>)}
              <span className="block pl-4 text-[12px] italic text-ink/50">“{l.evidence[0]?.quote}”</span>
            </li>
          ))}
          {!links.length && <li className="text-ink/50">No cause-effect link: each problem stands on its own.</li>}
        </ul>
      </div>
    </div>
  );
}

function ActionCard({ a, r }: { a: ScheduledAction; r: ResultV2 }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="rounded-xl border border-slate-200 bg-white p-3">
      <div className="flex flex-wrap items-start gap-2">
        <span className="font-semibold leading-snug">{a.label}</span>
        {a.original && <span className="chip">original idea</span>}
        {a.source === "auto_added" && <span className="chip">required first step</span>}
      </div>
      {a.plain && <p className="mt-1 text-[13px] text-ink/70">{a.plain}</p>}
      <p className="mt-1 text-[12px] text-ink/50">For: {a.scope}</p>
      {a.why_now && <p className="mt-2 rounded-lg bg-slate-50 px-2 py-1 text-[12px] text-ink/70"><b>Why now:</b> {a.why_now}</p>}
      {a.rationale && <p className="mt-1 text-[12px] text-ink/70"><b>Strategist:</b> {a.rationale}</p>}
      <div className="mt-2 flex flex-wrap gap-1.5">
        {a.fixes.map((f) => <span key={f} className="rounded-md bg-red-50 px-1.5 py-0.5 text-[11px] font-semibold text-red-700">fixes: {r.labels[f] ?? f}</span>)}
        {[...a.precedents, ...a.evidence.filter((e) => !a.precedents.includes(e))].map((e) => <Src key={e} id={e} r={r} />)}
      </div>
      {a.paths.length > 0 && (
        <button onClick={() => setOpen(!open)} className="mt-2 text-[12px] font-semibold text-brand">{open ? "▾" : "▸"} evidence path</button>
      )}
      {open && <ul className="mt-1 space-y-1 text-[12px] text-ink/70">{a.paths.map((p, i) => <li key={i}>• {p}</li>)}</ul>}
    </li>
  );
}

function Phases({ plan, r }: { plan: PlanV2; r: ResultV2 }) {
  return (
    <div className="grid gap-4 md:grid-cols-3">
      {[1, 2, 3].map((ph) => (
        <div key={ph} className="card p-4">
          <p className="eyebrow">{PHASE[ph]} phase</p>
          <p className="mt-1 text-[12px] text-ink/50">{ph === 1 ? "Measure and understand" : ph === 2 ? "Fix the causes" : "Amplify what now works"}</p>
          <ul className="mt-3 space-y-3">
            {plan.actions.filter((a) => a.phase === ph).map((a) => <ActionCard key={a.action + a.label} a={a} r={r} />)}
            {plan.actions.every((a) => a.phase !== ph) && <li className="text-sm text-ink/40">Nothing in this phase</li>}
          </ul>
        </div>
      ))}
    </div>
  );
}

export default function BriefView({ r: r0, runId, onRerun }: { r: ResultV2; runId: string; onRerun?: (f: Focus) => void }) {
  const [brief, setBrief] = useState(r0.brief);
  const [aud, setAud] = useState<Audience>(r0.audience ?? "board");
  const [memo, setMemo] = useState<Partial<Record<Audience, Brief>>>({});
  const [rewriting, setRewriting] = useState<Audience | null>(null);
  const [rwErr, setRwErr] = useState<string | null>(null);
  useEffect(() => {
    setBrief(r0.brief); setAud(r0.audience ?? "board");
    setMemo({ ...(r0.briefs ?? {}), [r0.audience ?? "board"]: r0.brief });
  }, [r0]);
  const r = useMemo(() => ({ ...r0, brief, audience: aud }), [r0, brief, aud]);
  const switchReader = async (a: Audience, retry = false) => {
    if (rewriting || (a === aud && !retry)) return;
    const known = memo[a];
    if (known && !retry) { setBrief(known); setAud(a); return; }           // already written for this reader: instant
    setRewriting(a); setRwErr(null);
    try {
      const x = await rewriteBriefV2(runId, a, retry);
      setMemo((m) => ({ ...m, [a]: x.brief })); setBrief(x.brief); setAud(a);
    } catch (e) { setRwErr(String(e)); } finally { setRewriting(null); }
  };
  const degraded = r0.degraded ?? [];
  const win = r.plans.find((p) => p.plan_id === r.winner)!;
  const c = r.client;
  const [showAll, setShowAll] = useState(false);
  const [openPlan, setOpenPlan] = useState<string | null>(null);
  const [showTrace, setShowTrace] = useState(false);
  const byP = useMemo(() => Object.fromEntries(r.problems.map((p) => [p.problem, p])), [r]);
  const accepted = r.confidence.map((x) => x.problem);
  const ordered = r.roots.causes.filter((x) => accepted.includes(x.problem));
  const shown = showAll ? ordered : ordered.filter((x) => x.role === "root" || x.role === "standalone").slice(0, 4);
  const issues = r.critic_rounds.flatMap((x) => x.issues);
  const st = r.stability;
  const download = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(r, null, 1)], { type: "application/json" }));
    Object.assign(document.createElement("a"), { href: url, download: `${runId}.json` }).click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-16">
      {/* 1 headline */}
      <div className="card-white">
        <p className="eyebrow">{c.industry}</p>
        <h2 className="mt-2 text-[30px] font-extrabold leading-tight">{r.brief.headline}</h2>
        <div className="mt-4 flex flex-wrap gap-2 text-[12px]">
          <span className={`rounded-full px-3 py-1 font-semibold ${st.same_as_previous === false ? "bg-red-100 text-red-700" : "bg-emerald-100 text-emerald-800"}`}>
            {st.same_as_previous == null ? "First analysis of this input" : st.same_as_previous ? `✓ Same answer as ${st.previous_runs} earlier run(s)` : "⚠ Differs from an earlier run"}
          </span>
          <span className="rounded-full bg-emerald-100 px-3 py-1 font-semibold text-emerald-800">✓ Every quote checked against the source</span>
          <span className="rounded-full bg-emerald-100 px-3 py-1 font-semibold text-emerald-800">✓ No number written by AI</span>
          <span className="rounded-full bg-slate-100 px-3 py-1 font-semibold text-ink/70">{r.critic_rounds.length} critic round(s) · {issues.length} issue(s) handled</span>
        </div>
        {degraded.length > 0 && (
          <div className="mt-4 rounded-xl border border-amber-300 bg-amber-50 p-3 text-[13px] text-amber-900">
            <b>Not every AI agent could run for this analysis:</b> {degraded.join(", ")}. Those steps used the rule-based
            result instead (usually because the free AI models reached their daily limit or the GPU server was off). Facts,
            numbers and safety rules are still correct, but the affected steps were not refined by AI: for example plans are
            not tailored to cohorts and the text is not reworded. Run again later for the full analysis.
          </div>
        )}
        {r.focus && Object.values(r.focus.effective).some((v) => v !== "normal") && (
          <p className="mt-3 text-[13px] text-ink/70"><b>Your priorities:</b> {PILLARS.map((p) => `${p.label}: ${r.focus!.effective[p.id]}`).join(" · ")}</p>
        )}
        {r.focus?.warnings.map((w, i) => <p key={i} className="mt-2 rounded-lg border border-amber-300 bg-amber-50 p-2.5 text-[13px] text-amber-800">⚠ {w}</p>)}
        <div className="mt-5 flex flex-col gap-3 border-t border-slate-200 pt-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-ink/50">Written for</p>
            <div className="mt-1 flex flex-wrap gap-1">
              {AUDIENCES.map((a) => (
                <button key={a.id} onClick={() => switchReader(a.id)} disabled={!!rewriting}
                  className={`rounded-full border px-3 py-1 text-[13px] font-semibold ${aud === a.id ? "border-brand bg-brand text-white" : "border-slate-200 text-ink/70 hover:border-brand"}`}>
                  {rewriting === a.id ? "Rewriting…" : a.label}
                </button>
              ))}
            </div>
            <p className="mt-1 text-[11px] text-ink/50">
              {rewriting ? `The AI writer is wording the brief for ${AUDIENCES.find((x) => x.id === rewriting)?.label} (can take up to a minute). Facts and numbers do not change.`
                : "Same facts and numbers for every reader; wording, emphasis and order follow the reader. Readers already written switch instantly."}
            </p>
            {!rewriting && brief.writer === "template" && (
              <p className="mt-1 text-[12px] text-amber-700">
                The AI writer was unavailable, so this is the rule-based wording for this reader (same verified facts).{" "}
                <button className="font-semibold underline" onClick={() => switchReader(aud, true)}>Try the AI writer again</button>
              </p>
            )}
            {rwErr && <p className="text-[12px] text-red-700">{rwErr}</p>}
          </div>
          <button className="btn shrink-0 px-5 py-2.5 text-[14px]" onClick={() => downloadPdf(r, runId)}>Download PDF</button>
        </div>
      </div>

      {/* 2 one minute */}
      <Section eyebrow="In one minute" title="The answer">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {r.brief.one_minute.map((k) => (
            <div key={k.title} className="card-white p-5">
              <p className="text-xs font-semibold uppercase tracking-wider text-brand">{k.title}</p>
              <p className="mt-2 font-semibold leading-snug">{k.text}</p>
              {k.detail && <p className="mt-2 text-[13px] text-ink/60">{k.detail}</p>}
            </div>
          ))}
        </div>
      </Section>

      {/* 3 chain */}
      <Section id="why" eyebrow="Diagnosis" title="What causes what"
        intro="Problems on the left drive the ones on the right. Fixing a root cause makes its symptoms improve without treating them directly. Every arrow comes from a case study, a research finding or the client's own words.">
        <Chain r={r} />
      </Section>

      {/* 4 evidence */}
      <Section eyebrow="Evidence" title="How we know"
        intro="Each problem is measured against the sector average. Confidence is high when the gap is measured AND backed by research or similar companies.">
        <div className="grid gap-4 lg:grid-cols-2">
          {shown.map((x) => {
            const p = byP[x.problem]; const conf = r.confidence.find((k) => k.problem === x.problem)!;
            const ch = r.challenges.find((k) => k.problem === x.problem);
            return (
              <div key={x.problem} className="card-white">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`rounded-full border px-2.5 py-0.5 text-[11px] font-semibold uppercase ${ROLE_TONE[x.role]}`}>{ROLE_TXT[x.role]}</span>
                  <span className={`rounded px-2 py-0.5 text-[11px] font-semibold uppercase ${CONF_TONE[conf.level]}`}>{conf.level} confidence</span>
                </div>
                <h3 className="mt-2 text-lg font-bold"><Term word={x.label} r={r} /></h3>
                <p className="text-[14px] text-ink/70">{x.plain}</p>
                <div className="mt-3 space-y-3">{p.measured.slice(0, 3).map((m) => <MetricBar key={m.key} m={m} />)}</div>
                {p.text.slice(0, 2).map((t, i) => <p key={i} className="mt-3 border-l-2 border-brand/40 pl-3 text-[13px] italic text-ink/70">“{t.quote}” <span className="not-italic text-ink/40">— {t.ref}</span></p>)}
                <p className="mt-3 text-[12px] text-ink/50">{conf.reason}. {conf.literature} research note(s), {conf.precedents} similar case(s).
                  {ch && ch.verdict !== "holds" && <> The skeptic agent found it <b>{ch.verdict}</b>: {ch.reason}</>}</p>
              </div>
            );
          })}
        </div>
        {ordered.length > shown.length || showAll ? (
          <button className="btn-ghost mt-4" onClick={() => setShowAll(!showAll)}>{showAll ? "Show only root causes" : `Show all ${ordered.length} problems`}</button>
        ) : null}
      </Section>

      {/* 5 plan */}
      <Section id="plan" eyebrow="The plan" title={win.title} intro={win.thesis}>
        <Phases plan={win} r={r} />
      </Section>

      {/* 6 not doing */}
      <Section eyebrow="Pushback" title="What we will not do, and why"
        intro="Some requests and ideas would waste money or backfire for this company right now. The rules decide; the explanation is in plain words.">
        <div className="card"><ul>
          {r.leadership.map((d, i) => {
            const tone = d.decision === "kept" ? "bg-emerald-50 text-emerald-700 border-emerald-200" : d.decision === "moved" ? "bg-amber-50 text-amber-700 border-amber-200" : "bg-red-50 text-red-700 border-red-200";
            const word = d.decision === "kept" ? "adopted" : d.decision === "moved" ? `later: ${PHASE[d.to_phase ?? 3]?.toLowerCase()} phase` : "not now";
            return (
              <li key={i} className="flex flex-col gap-1 border-b border-slate-200 py-3 last:border-0 sm:flex-row sm:gap-4">
                <span className={`w-fit shrink-0 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[11px] font-semibold uppercase ${tone}`}>{word}</span>
                <div><p className="font-semibold">Leadership asked for: {r.labels[d.intervention_id] ?? d.intervention_id}</p>
                  <p className="text-[13px] text-ink/70">{r.leadership_views[d.intervention_id] ?? d.reason}</p>
                  {r.leadership_views[d.intervention_id] && (
                    <details className="text-[12px] text-ink/40"><summary className="cursor-pointer">technical rule</summary>{d.reason}</details>)}</div>
              </li>
            );
          })}
          {(r.protected?.length ? r.protected : c.healthy_baselines).slice(0, 5).map((h, i) => (
            <li key={"h" + i} className="flex flex-col gap-1 border-b border-slate-200 py-3 last:border-0 sm:flex-row sm:gap-4">
              <span className="w-fit shrink-0 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-0.5 text-[11px] font-semibold uppercase text-emerald-700">protected</span>
              <p className="text-[14px]">{h}</p>
            </li>
          ))}
          {c.noise.map((n, i) => (
            <li key={"n" + i} className="flex flex-col gap-1 border-b border-slate-200 py-3 last:border-0 sm:flex-row sm:gap-4">
              <span className="w-fit shrink-0 rounded-full border border-slate-300 bg-white px-2.5 py-0.5 text-[11px] font-semibold uppercase text-ink/60">ignored data</span>
              <div><p className="text-[14px]">“{n.sentence}”</p><p className="text-[12px] text-ink/50">{n.reason}</p></div>
            </li>
          ))}
        </ul></div>
      </Section>

      {/* 6b tailor & test */}
      <Section id="tailor" eyebrow="Tailor & test" title="Try your own priorities and requests"
        intro="Change what matters most to you, or check an idea you are considering. Answers are instant and come from the same rules and evidence as the plan: no AI, nothing invented.">
        <Steer r={r} onRerun={(f) => onRerun?.(f)} />
      </Section>

      {/* 7 money */}
      <Section id="money" eyebrow="Money" title="What it costs and returns"
        intro="Benefits use the measured before/after results of similar companies applied to this client's own numbers. Costs are planning assumptions. No figure is produced by AI.">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[["Cost", eur(r.roi.cost_eur), "one-off, all phases"], ["Expected benefit", eur(r.roi.benefit_expected_eur), "per year"],
            ["Conservative benefit", eur(r.roi.benefit_conservative_eur), "per year, worst precedent"],
            ["Payback", r.roi.payback_months_expected == null ? "–" : `${r.roi.payback_months_expected.toFixed(1)} months`, "expected case"]].map(([k, v, s]) => (
            <div key={k} className="card-white p-5"><p className="text-xs font-semibold uppercase tracking-wider text-ink/50">{k}</p>
              <p className="mt-2 font-display text-2xl font-extrabold">{v}</p><p className="text-[12px] text-ink/50">{s}</p></div>
          ))}
        </div>
        <ul className="card mt-4 space-y-2 text-[14px]">
          {r.roi.lines.filter((l) => l.applies).map((l) => (
            <li key={l.name}><b>{l.name.replace(/_/g, " ")}:</b> {eur(l.benefit_expected_eur)} per year — {l.formula}{" "}
              {l.precedent_case_ids.map((id) => <span key={id} className="mr-1"><Src id={id} r={r} /></span>)}</li>
          ))}
          {!r.roi.lines.some((l) => l.applies) && <li className="text-ink/50">No precedent measured a money benefit for these actions.</li>}
        </ul>
      </Section>

      {/* 8 the written brief */}
      <Section eyebrow="Executive brief" title="The full story in plain words"
        intro={r.brief.writer === "llm_verified" ? "Written by the report-writer agent. Every sentence was checked: numbers come from the calculations, sources from the dataset." : "Generated from the verified results."}>
        <div className="card-white space-y-5">
          {r.brief.sections.map((s) => (
            <div key={s.heading}><h3 className="text-lg font-bold">{s.heading}</h3><p className="mt-1 text-[15px] leading-relaxed text-ink/80"><Cited text={s.text} r={r} /></p></div>
          ))}
        </div>
      </Section>

      {/* 9 quality control */}
      <Section eyebrow="Quality control" title="How the answer was checked"
        intro="Three safeguards: a plan critic that sends weak plans back to the strategist, a jury of stakeholders whose votes are audited, and a stability check that compares this answer with earlier runs on the same data.">
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="card">
            <p className="font-semibold">Plan critic</p>
            {r.critic_rounds.map((x) => (
              <p key={x.round} className="mt-2 text-[13px]">Round {x.round}: <b className={x.verdict === "pass" ? "text-emerald-700" : "text-amber-700"}>{x.verdict}</b> — {x.issues.filter((i) => i.severity === "blocking").length} blocking, {x.issues.filter((i) => i.severity === "minor").length} minor</p>
            ))}
            <details className="mt-2 text-[12px] text-ink/70"><summary className="cursor-pointer font-semibold text-brand">issues</summary>
              <ul className="mt-1 space-y-1">{issues.slice(0, 40).map((i, k) => <li key={k}>• [{i.by}] {i.plan_id} {i.target}: {i.detail}</li>)}</ul></details>
          </div>
          <div className="card">
            <p className="font-semibold">Jury & jury critic</p>
            <ul className="mt-2 space-y-1 text-[13px]">
              {r.ballots.map((b) => {
                const s = b.scores.find((x) => x.plan_id === r.winner);
                return <li key={b.persona}><b>{b.persona}</b>: {s ? `${s.verdict.replace(/_/g, " ")} — ${s.concern}` : "no vote"}</li>;
              })}
            </ul>
            {r.jury_audit && <details className="mt-2 text-[12px] text-ink/70"><summary className="cursor-pointer font-semibold text-brand">{r.jury_audit.flags.length} audit flag(s) · decided by {r.jury_audit.decided_by.replace(/_/g, " ")}</summary>
              <ul className="mt-1 space-y-1">{r.jury_audit.flags.map((f, k) => <li key={k}>• {f}</li>)}</ul></details>}
          </div>
          <div className="card">
            <p className="font-semibold">Stability</p>
            <p className="mt-2 text-[13px]">{st.same_as_previous == null ? "First run on this exact input. Run it again: the engine must give the same answer." : st.same_as_previous ? `Same decisions as the previous ${st.previous_runs} run(s) on identical data.` : "Different from an earlier run:"}</p>
            {st.differences.map((d, i) => <p key={i} className="mt-1 text-[12px] text-red-700">{d}</p>)}
            <p className="mt-2 text-[11px] text-ink/40">input fingerprint {st.fingerprint} · decision signature {st.signature}</p>
          </div>
        </div>
      </Section>

      {/* 10 alternatives */}
      <Section eyebrow="Alternatives" title="Other plans considered">
        <div className="space-y-3">
          {[...r.plans].sort((a, b) => (b.final ?? 0) - (a.final ?? 0)).map((p) => (
            <div key={p.plan_id} className="card p-0">
              <button className="flex w-full flex-wrap items-center justify-between gap-2 px-6 py-4 text-left" onClick={() => setOpenPlan(openPlan === p.plan_id ? null : p.plan_id)}>
                <span>{p.plan_id === r.winner && <span className="chip mr-2">chosen</span>}<b className="font-display text-lg">{p.title}</b> <span className="text-sm text-ink/50">({p.variant})</span></span>
                <span className="text-sm text-ink/60">covers {(p.coverage * 100).toFixed(0)}% · {eur(p.cost_eur)} · score {p.final?.toFixed(2)} {openPlan === p.plan_id ? "▾" : "▸"}</span>
              </button>
              {openPlan === p.plan_id && <div className="border-t border-slate-200 p-6"><p className="mb-4 text-ink/80">{p.thesis}</p><Phases plan={p} r={r} />
                {p.dropped.length > 0 && <p className="mt-3 text-[13px] text-ink/60">Dropped by the strategist: {p.dropped.map((d) => `${r.labels[d.action] ?? d.action} (${d.justification})`).join("; ")}</p>}</div>}
            </div>
          ))}
        </div>
      </Section>

      {/* 11 glossary + trace */}
      <Section eyebrow="Glossary" title="Words used in this report">
        <dl className="card grid gap-x-8 gap-y-3 md:grid-cols-2">
          {Object.entries(r.brief.glossary).slice(0, 30).map(([k, v]) => <div key={k}><dt className="font-semibold">{k}</dt><dd className="text-[13px] text-ink/70">{v}</dd></div>)}
        </dl>
      </Section>

      <section className="flex flex-wrap gap-3">
        <button className="btn-ghost" onClick={() => setShowTrace(!showTrace)}>{showTrace ? "Hide" : "Show"} engine trace</button>
        <button className="btn-ghost" onClick={download}>Download run JSON</button>
        {showTrace && (
          <div className="w-full overflow-x-auto rounded-2xl bg-ink p-5 text-[12px] text-slate-100">
            {r.trace.map((t) => (
              <div key={t.stage} className="mb-2"><b>{t.stage}</b> <span className="text-slate-400">[{t.kind}] {t.seconds}s {t.models.join(", ")} {t.cached ? "(replayed)" : ""}</span>
                {t.notes.slice(0, 8).map((n, i) => <div key={i} className="pl-4 text-slate-300">{n}</div>)}</div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
