import { jsPDF } from "jspdf";
import { AUDIENCES, PILLARS, type ResultV2 } from "./typesV2";

/** Standard PDF fonts only cover Latin-1: replace typographic characters so nothing renders as garbage. */
function clean(s: unknown): string {
  return String(s ?? "")
    .replace(/€\s?/g, "EUR ").replace(/[‐-―−]/g, "-").replace(/[‘’]/g, "'").replace(/[“”]/g, '"')
    .replace(/→/g, "->").replace(/←/g, "<-").replace(/≥/g, ">=").replace(/≤/g, "<=").replace(/[•●]/g, "-").replace(/…/g, "...")
    .replace(/×/g, "x").replace(/[▲▼▸▾⚠✓★]/g, "").replace(/[^\x09\x0A\x0D\x20-\x7E -ÿ]/g, "");
}
const eur = (v: number) => "EUR " + Math.round(v).toLocaleString("en-US");
const PHASE = ["", "First", "Second", "Third"];

export function downloadPdf(r: ResultV2, runId: string) {
  const doc = new jsPDF({ unit: "pt", format: "a4" });
  const W = doc.internal.pageSize.getWidth(), H = doc.internal.pageSize.getHeight(), M = 48, CW = W - 2 * M;
  let y = M;
  const ink: [number, number, number] = [30, 27, 75], brand: [number, number, number] = [79, 70, 229], grey: [number, number, number] = [100, 100, 120];

  const ensure = (h: number) => { if (y + h > H - M) { doc.addPage(); y = M; } };
  const text = (s: string, o: { size?: number; bold?: boolean; color?: [number, number, number]; indent?: number; gap?: number } = {}) => {
    const size = o.size ?? 10, indent = o.indent ?? 0;
    doc.setFont("helvetica", o.bold ? "bold" : "normal"); doc.setFontSize(size); doc.setTextColor(...(o.color ?? ink));
    const lines = doc.splitTextToSize(clean(s), CW - indent) as string[];
    for (const ln of lines) { ensure(size * 1.35); doc.text(ln, M + indent, y); y += size * 1.35; }
    y += o.gap ?? 4;
  };
  const heading = (s: string) => { ensure(40); y += 8; text(s, { size: 14, bold: true, color: brand, gap: 2 }); doc.setDrawColor(220, 220, 235); doc.line(M, y, W - M, y); y += 10; };
  const bullet = (s: string, indent = 10) => text("- " + s, { indent });

  const win = r.plans.find((p) => p.plan_id === r.winner)!;
  const reader = AUDIENCES.find((a) => a.id === r.audience)?.label ?? "Board members / Stakeholders";

  // cover
  text("Ingaze Action Recommendation Engine", { size: 10, color: grey });
  text(r.client.company_name, { size: 22, bold: true, gap: 2 });
  text(r.client.industry, { size: 11, color: grey });
  text(r.brief.headline, { size: 13, bold: true, gap: 8 });
  text(`Prepared for: ${reader}   |   ${new Date().toISOString().slice(0, 10)}   |   run ${runId}`, { size: 9, color: grey });
  const st = r.stability;
  text(st.same_as_previous == null ? "First analysis of this exact input." : st.same_as_previous
    ? `Same answer as ${st.previous_runs} earlier run(s) on identical data.` : "Differs from an earlier run on the same data.", { size: 9, color: grey });
  text("Every number is computed by Python from the data; every quote is checked against its source; no figure is written by AI.", { size: 9, color: grey, gap: 10 });
  if (r.focus && Object.values(r.focus.effective).some((v) => v !== "normal")) {
    text("Client priorities: " + PILLARS.map((p) => `${p.label}: ${r.focus!.effective[p.id]}`).join("; "), { size: 9, bold: true });
  }
  r.focus?.warnings.forEach((w) => text("Warning: " + w, { size: 9, color: [160, 90, 0] }));
  if (r.degraded?.length) text(`Note: these AI agents could not run and their steps used the rule-based result: ${r.degraded.join(", ")}. Facts and numbers are unaffected.`, { size: 9, color: [160, 90, 0] });
  if (r.brief.writer === "template") text("The brief below uses the rule-based wording (the AI writer was unavailable).", { size: 9, color: [160, 90, 0] });

  heading("The answer in one minute");
  r.brief.one_minute.forEach((k) => { text(k.title, { bold: true, gap: 0 }); text(k.text, { indent: 10, gap: 0 }); if (k.detail) text(k.detail, { indent: 10, size: 9, color: grey }); });

  heading("Executive brief");
  r.brief.sections.forEach((s) => { text(s.heading, { bold: true, size: 11, gap: 1 }); text(s.text, { gap: 8 }); });

  heading("Root causes and how we know");
  r.roots.causes.filter((x) => r.confidence.some((c) => c.problem === x.problem)).forEach((x) => {
    const conf = r.confidence.find((c) => c.problem === x.problem)!;
    const p = r.problems.find((q) => q.problem === x.problem);
    text(`${x.label}  (${x.role}, ${conf.level} confidence)`, { bold: true, gap: 0 });
    text(x.plain, { indent: 10, size: 9, gap: 0 });
    p?.measured.slice(0, 2).forEach((m) => bullet(`${m.label}: ${m.value}${m.peer != null ? ` vs peers ${m.peer}` : ""}`, 10));
    y += 3;
  });

  heading("What causes what");
  r.roots.links.forEach((l) => {
    text(`${r.labels[l.source] ?? l.source} -> ${r.labels[l.target] ?? l.target}: ${l.mechanism}`, { gap: 0 });
    text(`"${l.evidence[0]?.quote ?? ""}" [${l.origin === "client_text" ? "client's own words" : l.evidence.map((e) => e.ref).join(", ")}]`, { indent: 10, size: 8, color: grey });
  });

  heading(`The plan: ${win.title}`);
  text(win.thesis, { gap: 6 });
  [1, 2, 3].forEach((ph) => {
    const acts = win.actions.filter((a) => a.phase === ph);
    if (!acts.length) return;
    text(`${PHASE[ph]} phase`, { bold: true, size: 11 });
    acts.forEach((a) => {
      text(a.label + (a.original ? "  (original idea)" : ""), { bold: true, indent: 10, gap: 0 });
      if (a.plain) text(a.plain, { indent: 20, size: 9, gap: 0 });
      text(`For: ${a.scope}.  Why now: ${a.why_now}`, { indent: 20, size: 9, color: grey, gap: 0 });
      const src = [...a.precedents, ...a.evidence.filter((e) => !a.precedents.includes(e))];
      if (a.fixes.length || src.length) text(`Fixes: ${a.fixes.map((f) => r.labels[f] ?? f).join(", ") || "-"}.  Sources: ${src.join(", ") || "-"}`, { indent: 20, size: 9, color: grey });
      y += 2;
    });
  });

  heading("What we will not do, and why");
  r.leadership.forEach((d) => {
    const word = d.decision === "kept" ? "adopted" : d.decision === "moved" ? `later (${PHASE[d.to_phase ?? 3]?.toLowerCase()} phase)` : "not now";
    text(`Request: ${r.labels[d.intervention_id] ?? d.intervention_id} - ${word}`, { bold: true, gap: 0 });
    text(r.leadership_views[d.intervention_id] ?? d.reason, { indent: 10, size: 9 });
  });
  (r.protected?.length ? r.protected : r.client.healthy_baselines).slice(0, 5).forEach((h) => bullet("Protected: " + h));

  heading("What it costs and returns");
  text(`Cost: ${eur(r.roi.cost_eur)}   |   Expected benefit: ${eur(r.roi.benefit_expected_eur)} per year   |   Conservative: ${eur(r.roi.benefit_conservative_eur)} per year` +
    (r.roi.payback_months_expected ? `   |   Payback: ${r.roi.payback_months_expected.toFixed(1)} months` : ""), { bold: true });
  r.roi.lines.filter((l) => l.applies).forEach((l) => bullet(`${l.name.replace(/_/g, " ")}: ${eur(l.benefit_expected_eur)} per year - ${l.formula} [${l.precedent_case_ids.join(", ")}]`));
  text("Costs are planning assumptions (data/assumptions.json); benefits apply measured results of similar companies to this client's numbers.", { size: 8, color: grey });

  heading("How the answer was checked");
  r.critic_rounds.forEach((c) => bullet(`Plan critic, round ${c.round}: ${c.verdict} (${c.issues.filter((i) => i.severity === "blocking").length} blocking, ${c.issues.filter((i) => i.severity === "minor").length} minor issues)`));
  if (r.jury_audit) bullet(`Jury of five stakeholders audited: ${r.jury_audit.flags.length} flag(s); winner decided by ${r.jury_audit.decided_by.replace(/_/g, " ")}.`);
  r.ballots.forEach((b) => { const s = b.scores.find((x) => x.plan_id === r.winner); if (s) bullet(`${b.persona}: ${s.verdict.replace(/_/g, " ")} - ${s.concern}`, 20); });
  for (const [name, fc] of [["plans and explanations", r.fact_check], ["this brief", r.brief.fact_check]] as const) {
    if (fc) bullet(`Fact-checker on ${name}: ` + (fc.status === "ran" ? `${fc.checked} AI-written sentence(s) checked with ${fc.checker_model || "a second model"}, ${fc.removed.length} removed, ${fc.citations_removed.length} irrelevant citation(s) removed.`
      : fc.status === "unavailable" ? "AI checker unavailable; citation check applied." : "nothing AI-written to check."));
  }
  bullet(`Input fingerprint ${st.fingerprint}, decision signature ${st.signature}.`);

  heading("Sources");
  Object.entries(r.documents).sort(([a], [b]) => a.localeCompare(b, "en", { numeric: true })).forEach(([id, d]) => {
    text(`[${id}] ${d.title}`, { bold: true, size: 9, gap: 0 });
    text(d.text, { indent: 10, size: 8, color: grey });
  });

  heading("Glossary");
  Object.entries(r.brief.glossary).slice(0, 30).forEach(([k, v]) => { text(k, { bold: true, size: 9, gap: 0 }); text(v, { indent: 10, size: 9 }); });

  const pages = doc.getNumberOfPages();
  for (let i = 1; i <= pages; i++) {
    doc.setPage(i); doc.setFont("helvetica", "normal"); doc.setFontSize(8); doc.setTextColor(...grey);
    doc.text(clean(`${r.client.company_name} - Ingaze evidence engine`), M, H - 24);
    doc.text(`${i} / ${pages}`, W - M, H - 24, { align: "right" });
  }
  doc.save(`${runId}_${r.audience}.pdf`);
}
