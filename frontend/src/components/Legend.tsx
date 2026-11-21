import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { BADGE_NEUTRAL, BADGE_OK, CONF_TONE, DECISION_TONE, FIX_CLASS, PILL, ROLE_TONE, ROLE_TXT, SRC_CLASS, STATUS_TONE, VERDICT_TONE } from "./tones";

export interface LegendItem { sample: ReactNode; text: ReactNode }

/** "Show all explanations" switch in the header opens every legend at once. */
export const LegendContext = createContext<boolean>(false);

export function Legend({ items, title = "How to read this section" }: { items: LegendItem[]; title?: string }) {
  const all = useContext(LegendContext);
  const [open, setOpen] = useState(all);
  useEffect(() => setOpen(all), [all]);
  return (
    <div className="mt-3">
      <button onClick={() => setOpen(!open)} aria-expanded={open}
        className="inline-flex items-center gap-1.5 rounded-full border border-brand/30 bg-brand-soft px-3 py-1 text-[12px] font-semibold text-brand hover:bg-brand hover:text-white">
        <span aria-hidden className="flex h-4 w-4 items-center justify-center rounded-full border border-current text-[10px]">i</span>
        {title} {open ? "▾" : "▸"}
      </button>
      {open && (
        <div className="mt-2 grid gap-x-6 gap-y-2.5 rounded-xl border border-slate-200 bg-white p-4 text-[13px] md:grid-cols-2">
          {items.map((it, i) => (
            <div key={i} className="flex items-start gap-3">
              <div className="flex min-w-[118px] shrink-0 flex-wrap items-center gap-1 pt-0.5">{it.sample}</div>
              <div className="text-ink/75">{it.text}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------- samples rendered with the page's own styles ----------
const Src = ({ id }: { id: string }) => <span className={SRC_CLASS}>{id}</span>;
const Pill = ({ tone, children }: { tone: string; children: ReactNode }) => <span className={`${PILL} ${tone}`}>{children}</span>;
const Role = ({ role }: { role: string }) => <span className={`rounded-full border px-2.5 py-0.5 text-[11px] font-semibold uppercase ${ROLE_TONE[role]}`}>{ROLE_TXT[role]}</span>;
const Conf = ({ level, word = "" }: { level: string; word?: string }) => <span className={`rounded px-2 py-0.5 text-[11px] font-semibold uppercase ${CONF_TONE[level]}`}>{level}{word}</span>;
const Chip = ({ children }: { children: ReactNode }) => <span className="chip">{children}</span>;
const Txt = ({ children, className = "" }: { children: ReactNode; className?: string }) => <span className={`text-[12px] font-semibold ${className}`}>{children}</span>;

export const SOURCES: LegendItem[] = [
  { sample: <Src id="C05" />, text: <><b>C = case study.</b> A real company from the dataset with a similar problem and measured before/after results. Hover the tag to read it.</> },
  { sample: <Src id="R4" />, text: <><b>R = research finding.</b> An empirical result from HR research (e.g. "360 feedback plus coaching cuts attrition risk by 18–28%").</> },
  { sample: <Src id="FN1" />, text: <><b>FN = field note.</b> An expert rule from practice (e.g. "diagnose before you redesign", "amplify only what already works").</> },
  { sample: <Chip>client's own words</Chip>, text: "The link comes from the company's own data (a sentence it wrote), not from a document." },
];

export const LEGENDS: Record<string, LegendItem[]> = {
  header: [
    { sample: <span className={BADGE_OK}>✓ Same answer…</span>, text: "Asked again with the same data and priorities, the engine gave the same decisions. 'First analysis' means this exact input is new." },
    { sample: <span className={BADGE_OK}>✓ Quotes checked</span>, text: "Every quote shown was found word for word in the company data or in the source document." },
    { sample: <span className={BADGE_OK}>✓ No number by AI</span>, text: "All figures (metrics, costs, benefits, payback) are calculated by the engine, never written by an AI model." },
    { sample: <span className={BADGE_OK}>✓ Fact-checked</span>, text: "Number of AI-written sentences checked by an independent fact-checker; unsupported ones were removed." },
    { sample: <span className={BADGE_NEUTRAL}>critic rounds</span>, text: "How many times the plan critic reviewed the plans and how many issues it raised and got fixed." },
    { sample: <Txt className="text-amber-700">⚠ amber box</Txt>, text: "Something to know: an AI step that could not run, or a warning about the priorities you chose." },
  ],
  minute: [
    { sample: <Txt className="text-brand">THE ROOT CAUSES</Txt>, text: "The problems that drive the others. Fixing them fixes most of what is wrong." },
    { sample: <Txt className="text-brand">THE FIRST MOVE</Txt>, text: "What to do in the first phase. It is usually measurement: the plan diagnoses before it changes things." },
    { sample: <Txt className="text-brand">THE PAYOFF</Txt>, text: "Cost of the plan and the yearly benefit expected from similar companies' measured results." },
    { sample: <Txt className="text-brand">WHAT WE PUSH BACK ON</Txt>, text: "A request from leadership the evidence advises against, or advises to postpone." },
  ],
  diagnosis: [
    { sample: <Role role="root" />, text: "Root cause: it drives other problems and is driven by none. Fix these first." },
    { sample: <Role role="standalone" />, text: "A real problem not linked to the others. It needs its own fix." },
    { sample: <Role role="intermediate" />, text: "In between: caused by a root cause and causing a symptom." },
    { sample: <Role role="symptom" />, text: "Symptom: a consequence. It improves when its causes are fixed, so it gets no separate action." },
    { sample: <><Conf level="high" /><Conf level="medium" /><Conf level="low" /></>, text: "How sure the engine is that the problem is real (explained in “How we know”)." },
    { sample: <Txt className="text-brand">A → B</Txt>, text: "A causes or worsens B. Click a problem to see only its links, each with the sentence that proves it." },
    ...SOURCES,
  ],
  evidence: [
    { sample: <Conf level="high" word=" confidence" />, text: "Measured worse than sector peers AND backed by at least two research findings or similar companies, and not disputed by the skeptic agent." },
    { sample: <Conf level="medium" word=" confidence" />, text: "Measured against peers but with little outside evidence, or challenged by the skeptic agent, or stated by the company and backed by research." },
    { sample: <Conf level="low" word=" confidence" />, text: "Only mentioned in the company's own text; no metric confirms it." },
    { sample: <span className="flex flex-col gap-1"><span className="h-2.5 w-16 rounded-full bg-brand" /><span className="h-2.5 w-10 rounded-full bg-slate-300" /></span>, text: "Blue bar = the company, grey bar = sector average (peers), on the same scale." },
    { sample: <><Txt className="text-red-600">% worse</Txt><Txt className="text-emerald-600">% better</Txt></>, text: "How far the company is from the sector average, in the direction that matters (for some metrics lower is better)." },
    { sample: <Txt className="text-red-700">⚠ threshold</Txt>, text: "A research threshold is crossed (e.g. a promise-vs-reviews gap above 1.1 stars), so the problem is severe." },
    { sample: <Txt className="italic text-ink/70">“quote” — signals.x</Txt>, text: "A sentence from the company data. signals = Ingaze platform data, internal = the company's internal notes, narrative = its situation summary." },
    { sample: <Txt>holds / weaker / refuted</Txt>, text: "What the skeptic agent concluded when it tried to disprove the problem. 'Refuted' only counts with verified counter-evidence." },
    { sample: <Role role="root" />, text: "The role of the problem in the cause-and-effect chain (see “What causes what”)." },
  ],
  plan: [
    { sample: <Txt className="text-brand">FIRST / SECOND / THIRD PHASE</Txt>, text: "Order of the plan: first measure and understand, then fix the causes, then amplify what works. The rules set the order, not the AI." },
    { sample: <Chip>original idea</Chip>, text: "A new action proposed for this company that is not in the standard catalog. It passed the plan critic and the fact-checker and cites its evidence." },
    { sample: <Chip>required first step</Chip>, text: "Added automatically because another action in the plan needs it first (e.g. coaching managers needs a 360 survey to know who to coach)." },
    { sample: <span className={FIX_CLASS}>fixes: …</span>, text: "The problem(s) this action addresses." },
    { sample: <Src id="C05" />, text: "Evidence behind the action: similar companies that used it (C) and research (R) or field notes (FN). Hover to read." },
    { sample: <Txt>For: …</Txt>, text: "Who the action targets: the whole company or named sites and teams." },
    { sample: <Txt>Why now</Txt>, text: "Why the action sits in this phase (diagnostics first, prerequisites, or waiting for trust to be fixed)." },
    { sample: <Txt>Strategist</Txt>, text: "The strategist agent's reason for this action, checked by the fact-checker." },
    { sample: <Txt className="text-brand">▸ evidence path</Txt>, text: "Click to see the chain from the action to the problem it fixes and the companies where it worked." },
    ...SOURCES.slice(0, 3),
  ],
  pushback: [
    { sample: <Pill tone={DECISION_TONE.adopted}>adopted</Pill>, text: "The leadership request is part of the plan as asked." },
    { sample: <Pill tone={DECISION_TONE.later}>later: third phase</Pill>, text: "A good idea at the wrong time: it can start only in the phase shown (e.g. after trust problems are fixed)." },
    { sample: <Pill tone={DECISION_TONE.no}>not now</Pill>, text: "Advised against for this company: it does not fit the workforce, or it would change something that already works." },
    { sample: <Pill tone={DECISION_TONE.protected}>protected</Pill>, text: "A strength that is better than the sector average. The plan deliberately leaves it alone." },
    { sample: <Pill tone={DECISION_TONE.ignored}>ignored data</Pill>, text: "Information the engine set aside as unreliable or irrelevant for this workforce, with the reason." },
    { sample: <Txt className="text-ink/40">technical rule</Txt>, text: "Click to see the exact rule the engine applied." },
  ],
  tailor: [
    { sample: <Txt>Less · Normal · More</Txt>, text: "Your priority per area. More adds every allowed action for that area and starts it as early as the rules allow; Less defers its problems. Facts and safety rules never change." },
    { sample: <><Txt className="text-emerald-700">▲ 2</Txt><Txt className="text-red-600">▼ 1</Txt></>, text: "How many places a problem moved up or down in the order of importance compared with neutral priorities." },
    { sample: <Chip>deferred by you</Chip>, text: "A problem you chose to put later. It remains a real problem in the diagnosis." },
    { sample: <><Txt className="text-emerald-700">+</Txt><Txt className="text-red-600">−</Txt><Txt className="text-amber-700">↔</Txt></>, text: "Action added, removed, or moved to another phase compared with the neutral plan." },
    { sample: <span className={`rounded-md border px-2 py-0.5 text-[11px] font-semibold ${VERDICT_TONE.yes_now}`}>Yes / Already planned</span>, text: "Your request can go ahead, or is already in the plan." },
    { sample: <span className={`rounded-md border px-2 py-0.5 text-[11px] font-semibold ${VERDICT_TONE.later}`}>Not now</span>, text: "Your request should wait until the phase shown." },
    { sample: <span className={`rounded-md border px-2 py-0.5 text-[11px] font-semibold ${VERDICT_TONE.no}`}>No</span>, text: "Your request is advised against for this company, with the reason and the source." },
    { sample: <Chip>interpreted</Chip>, text: "No action name was found word for word, so the closest action(s) were chosen by the words in common. Check it is what you meant." },
    { sample: <span className={`rounded-md border px-2 py-0.5 text-[11px] font-semibold ${STATUS_TONE.allowed}`}>possible now</span>, text: "In the list of known actions: what the rules allow for this company (now, later, or not at all)." },
  ],
  money: [
    { sample: <Txt>Cost</Txt>, text: "One-off cost of all actions, from planning assumptions per action." },
    { sample: <Txt>Expected benefit</Txt>, text: "Yearly gain if results match the average of similar companies, applied to this company's own figures." },
    { sample: <Txt>Conservative</Txt>, text: "Yearly gain if results match the weakest similar company: a safe lower estimate." },
    { sample: <Txt>Payback</Txt>, text: "Months until the expected yearly benefit has repaid the cost." },
    { sample: <Txt>formula</Txt>, text: "Each benefit line shows how it is calculated and which case studies (C) its percentages come from." },
    { sample: <Src id="C05" />, text: "The similar company whose measured result is used in the calculation." },
  ],
  brief: [
    { sample: <Src id="FN5" />, text: "Source of the sentence. Hover to read what the document actually says." },
    { sample: <Txt>AI-written</Txt>, text: "Worded by the report-writer agent for the reader you chose; every number comes from the engine and every sentence was fact-checked." },
    { sample: <Txt className="text-amber-700">rule-based</Txt>, text: "If the AI writer was unavailable, the engine's own wording is used: same facts, simpler style." },
    ...SOURCES.slice(0, 3),
  ],
  quality: [
    { sample: <><Txt className="text-emerald-700">pass</Txt><Txt className="text-amber-700">revise</Txt></>, text: "Plan critic verdict per round: revise sends the plans back to the strategist with the issues to fix." },
    { sample: <Txt>blocking / minor</Txt>, text: "Blocking issues must be fixed (wrong or unsupported advice); minor ones are improvements." },
    { sample: <Txt>[rules] / [llm]</Txt>, text: "Whether the issue was found by an automatic rule check or by the AI critic." },
    { sample: <Txt>approve · with changes · reject</Txt>, text: "Each jury persona's verdict on the chosen plan, with its main concern." },
    { sample: <Txt>audit flags</Txt>, text: "Votes the jury critic down-weighted: they cited nothing in the plan, contradicted their own scores, or were outliers." },
    { sample: <Txt>decided by</Txt>, text: "Jury: the jury's audited scores decided. Deterministic tie-break: the plans were too close, so the engine's own score decided, for a stable answer." },
    { sample: <Txt>fingerprint / signature</Txt>, text: "Codes for the exact input and the decisions. Same fingerprint + same signature = same answer." },
    { sample: <Txt>unsupported · contradicted</Txt>, text: "Fact-checker verdicts that remove a sentence: it adds a claim not in the evidence, or conflicts with it." },
  ],
  alternatives: [
    { sample: <Chip>chosen</Chip>, text: "The plan the engine recommends (best combined score of the jury and the engine's own checks)." },
    { sample: <Txt>(focus)</Txt>, text: "Follows your priorities." },
    { sample: <Txt>(full)</Txt>, text: "Fixes every root cause and the problems in between." },
    { sample: <Txt>(core)</Txt>, text: "Only the three highest-priority root causes." },
    { sample: <Txt>(lean)</Txt>, text: "Covers the root causes at the lowest cost." },
    { sample: <Txt>(quick)</Txt>, text: "Only actions that can start in the first two phases." },
    { sample: <Txt>covers %</Txt>, text: "Share of the root causes (weighted by importance) the plan addresses." },
    { sample: <Txt>score</Txt>, text: "Combined score from 0 to 1: half the audited jury, half the engine's checks (coverage, evidence, cost-efficiency)." },
  ],
};
