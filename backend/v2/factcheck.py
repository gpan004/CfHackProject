"""Fact-checker: the last line of defence against hallucination in text the client reads.

Layer 1 (no AI): citation grounding - a [C05]-style citation is removed when the cited document is not linked in the
knowledge graph to any problem or action the sentence talks about (kg.ground_citations).
Layer 2 (AI, a different model family from the writer): every AI-written sentence is checked against the verified
facts and marked supported / unsupported / contradicted. Unsupported and contradicted sentences are removed or replaced
by the rule-based version. Sentences produced by Python's own template are facts already and are not sent.

The deterministic checks always win: the AI checker can only remove text, never add or restore it. If the checker is
unavailable, layer 1 and all earlier checks still apply, and the page says so.
"""
from .kg import ground_citations  # noqa: F401  (re-exported for the pipeline)
from .llm import call
from . import prompts as P
from .schemas import FactCheckDraft, FactCheckReport, CheckedItem

CHECKER_TIER = "local"      # the writer and strategist run on 'remote' (OpenRouter): the checker uses the other family


async def check(items: list[tuple[str, str]], facts_text: str, role: str, trace_calls) -> tuple[dict[int, object], str]:
    """items: [(where, sentence)]. Returns ({index: ClaimVerdict}, model). Raises on failure (caller degrades)."""
    if not items:
        return {}, ""
    sents = "\n".join(f"{i}. [{where}] {s}" for i, (where, s) in enumerate(items))
    user = f"FACTS (verified by Python; the only source of truth):\n{facts_text}\n\nSENTENCES TO CHECK:\n{sents}"
    obj, info = await call(role, CHECKER_TIER, P.FACT_CHECKER, user, FactCheckDraft)
    trace_calls.append(info)
    return {v.id: v for v in obj.verdicts if 0 <= v.id < len(items)}, info.get("model", "")


def ground(text: str, where: str, report: FactCheckReport) -> str:
    out, removed = ground_citations(text)
    report.citations_removed += [f"{where}: {r}" for r in removed]
    return out


async def run(items: list[tuple[str, str]], facts_text: str, role: str, trace_calls,
              report: FactCheckReport | None = None) -> tuple[list[str | None], FactCheckReport]:
    """Checks the items. Returns (texts with None for removed ones, report). Never raises."""
    report = report or FactCheckReport()
    texts = [ground(t, w, report) for w, t in items]
    todo = [(i, (w, t)) for i, (w, t) in enumerate(zip([w for w, _ in items], texts)) if t and t.strip()]
    if not todo:
        if report.status != "ran":
            report.status = "nothing_to_check"
        return texts, report
    try:
        verdicts, model = await check([x for _, x in todo], facts_text, role, trace_calls)
    except Exception as e:  # noqa: BLE001 - degrade: layer 1 and the earlier deterministic checks still apply
        report.status, report.note = "unavailable", f"fact-checker unavailable ({str(e)[:120]})"
        return texts, report
    report.status, report.checker_model = "ran", model or report.checker_model
    if model and "mistral" not in model.lower():
        note = "the independent checker model (local Mistral) was unreachable, so the check ran on the same model family as the writer"
        if note not in report.note:
            report.note = (report.note + " " if report.note else "") + note + "."
    report.checked += len(todo)
    for k, (i, (where, t)) in enumerate(todo):
        v = verdicts.get(k)
        if v is not None and v.verdict in ("unsupported", "contradicted"):
            report.removed.append(CheckedItem(where=where, text=t, verdict=v.verdict, reason=v.reason[:300],
                                              action="removed"))
            texts[i] = None
    missing = len(todo) - len(verdicts)
    if missing > 0:
        report.note = (report.note + " " if report.note else "") + f"{missing} sentence(s) got no verdict and were kept."
    return texts, report
