/** Shared tag styles: the results page and its legends use the same classes, so a legend shows a tag exactly as it appears. */
export const ROLE_TXT: Record<string, string> = { root: "Root cause", standalone: "Standalone problem", intermediate: "In between", symptom: "Symptom" };
export const ROLE_TONE: Record<string, string> = {
  root: "border-red-300 bg-red-50 text-red-800", standalone: "border-orange-300 bg-orange-50 text-orange-800",
  intermediate: "border-amber-300 bg-amber-50 text-amber-800", symptom: "border-slate-300 bg-slate-50 text-slate-700",
};
export const CONF_TONE: Record<string, string> = { high: "bg-emerald-100 text-emerald-800", medium: "bg-amber-100 text-amber-800", low: "bg-slate-200 text-slate-700" };
export const SRC_CLASS = "cursor-help rounded-md border border-brand/20 bg-brand-soft px-1.5 py-0.5 text-[11px] font-semibold text-brand";
export const FIX_CLASS = "rounded-md bg-red-50 px-1.5 py-0.5 text-[11px] font-semibold text-red-700";
export const PILL = "w-fit shrink-0 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[11px] font-semibold uppercase";
export const DECISION_TONE = {
  adopted: "bg-emerald-50 text-emerald-700 border-emerald-200", later: "bg-amber-50 text-amber-700 border-amber-200",
  no: "bg-red-50 text-red-700 border-red-200", protected: "border-emerald-200 bg-emerald-50 text-emerald-700",
  ignored: "border-slate-300 bg-white text-ink/60",
};
export const VERDICT_TONE: Record<string, string> = {
  yes_now: "border-emerald-200 bg-emerald-50 text-emerald-800", already_planned: "border-emerald-200 bg-emerald-50 text-emerald-800",
  later: "border-amber-200 bg-amber-50 text-amber-800", no: "border-red-200 bg-red-50 text-red-700",
};
export const STATUS_TONE: Record<string, string> = {
  allowed: "border-emerald-200 bg-emerald-50 text-emerald-800", later: "border-amber-200 bg-amber-50 text-amber-800",
  not_for_this_company: "border-slate-200 bg-slate-50 text-ink/50",
};
export const BADGE_OK = "rounded-full bg-emerald-100 px-3 py-1 font-semibold text-emerald-800";
export const BADGE_NEUTRAL = "rounded-full bg-slate-100 px-3 py-1 font-semibold text-ink/70";
