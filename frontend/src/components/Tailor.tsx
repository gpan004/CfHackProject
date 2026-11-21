import { AUDIENCES, PILLARS, focusWarning, type Audience, type Focus, type FocusLevel } from "../typesV2";

const LEVELS: { id: FocusLevel; label: string }[] = [{ id: "less", label: "Less" }, { id: "normal", label: "Normal" }, { id: "more", label: "More" }];

/** Three-way switch per pillar: Less · Normal · More, with the live "not effective" warning. */
export function FocusSwitches({ focus, onChange, disabled = false, compact = false }:
  { focus: Focus; onChange: (f: Focus) => void; disabled?: boolean; compact?: boolean }) {
  const warn = focusWarning(focus);
  return (
    <div>
      <div className="space-y-2">
        {PILLARS.map((p) => (
          <div key={p.id} className={compact ? "flex items-center justify-between gap-3" : ""}>
            <p className={`text-[13px] font-medium ${compact ? "" : "mb-1"}`}>{p.label}</p>
            <div className="grid shrink-0 grid-cols-3 gap-1 rounded-lg border border-slate-200 bg-slate-50 p-0.5 text-[12px] font-semibold">
              {LEVELS.map((l) => (
                <button key={l.id} disabled={disabled} onClick={() => onChange({ ...focus, [p.id]: l.id })}
                  className={`rounded-md px-2.5 py-1 transition ${focus[p.id] === l.id
                    ? l.id === "more" ? "bg-brand text-white" : l.id === "less" ? "bg-slate-500 text-white" : "bg-white text-ink shadow"
                    : "text-ink/50 hover:text-ink"}`}>{l.label}</button>
              ))}
            </div>
          </div>
        ))}
      </div>
      {warn && <p className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-2.5 text-[12px] text-amber-800">⚠ {warn}</p>}
      <p className="mt-2 text-[11px] text-ink/50">Priorities change what comes first. They never change the facts, the evidence or the safety rules.</p>
    </div>
  );
}

/** Who will read the answer: same facts and numbers, different order, wording and emphasis. */
export function AudiencePicker({ value, onChange, disabled = false }: { value: Audience; onChange: (a: Audience) => void; disabled?: boolean }) {
  return (
    <div className="grid gap-1">
      {AUDIENCES.map((a) => (
        <label key={a.id} className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-[13px] ${value === a.id ? "border-brand bg-brand-soft font-semibold text-brand" : "border-slate-200 bg-white"}`}>
          <input type="radio" className="accent-brand" checked={value === a.id} disabled={disabled} onChange={() => onChange(a.id)} />
          {a.label}
        </label>
      ))}
    </div>
  );
}
