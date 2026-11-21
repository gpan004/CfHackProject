"""Embeddings + alignment matrices (§6.10)."""
import numpy as np

from .config import EMBED_MODEL, W_CASE, W_SNIP, TOP_K_LLM_VERIFY, N_TOP_CASES, N_TOP_SNIPPETS, N_FIELD_NOTES
from .knowledge import tag_concepts, jaccard, concepts_of
from .schemas import Alignment

_model = None
_corpus = {}


def model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBED_MODEL)
    return _model


def embed(texts: list[str], prefix: str) -> np.ndarray:
    if not texts:
        return np.zeros((0, 384))
    return np.asarray(model().encode([prefix + t for t in texts], normalize_embeddings=True))


def case_text(c) -> str:
    return c.problem + " Interventions: " + " ".join(s.text for s in c.interventions) + " Results: " + c.measured_roi_text


def build_corpus(a: dict):
    """Called once at startup."""
    _corpus["cases"] = embed([case_text(c) for c in a["cases"]], "passage: ")
    _corpus["snippets"] = embed([s.finding for s in a["snippets"]], "passage: ")


def rc_text(rc) -> str:
    h = rc.hypothesis
    return h.statement + " " + " ".join(e.quote for e in h.evidence)


def rc_concepts(rc) -> set[str]:
    return set(rc.hypothesis.concepts) | set(tag_concepts(rc.hypothesis.statement))


def _sem(Q, D):
    cos = Q @ D.T
    lo, hi = cos.min(1, keepdims=True), cos.max(1, keepdims=True)
    return (cos - lo) / np.maximum(hi - lo, 1e-9)


def prelim(roots, client, a: dict) -> dict:
    if "cases" not in _corpus:
        build_corpus(a)
    Q = embed([rc_text(r) for r in roots], "query: ")
    g = a["graph"]
    out = {}
    for kind, docs in (("cases", a["cases"]), ("snippets", a["snippets"])):
        sem = _sem(Q, _corpus[kind]) if len(roots) else np.zeros((0, len(docs)))
        concept = np.array([[jaccard(rc_concepts(r), concepts_of(g, d.id)) for d in docs] for r in roots]).reshape(len(roots), len(docs))
        fit = np.array([1.0 if (not d.archetypes or set(d.archetypes) & set(client.archetypes)) else 0.0 for d in docs])
        out[kind] = {"sem": sem, "concept": concept, "fit": fit}
    return out


def llm_candidates(roots, p: dict, a: dict) -> dict[str, list]:
    """Top-K fitting cases per root cause by 0.5*sem + 0.5*concept."""
    c = p["cases"]
    res = {}
    for i, r in enumerate(roots):
        pre = (0.5 * c["sem"][i] + 0.5 * c["concept"][i]) * c["fit"]
        order = [j for j in np.argsort(-pre) if c["fit"][j] == 1][:TOP_K_LLM_VERIFY]
        res[r.hypothesis.id] = [a["cases"][j] for j in order]
    return res


def finalize(roots, p: dict, a: dict, ratings: dict[tuple[str, str], int]) -> dict:
    cases, snips = a["cases"], a["snippets"]
    c, s = p["cases"], p["snippets"]
    llm = np.array([[ratings.get((r.hypothesis.id, d.id), 0) / 3.0 for d in cases] for r in roots]).reshape(len(roots), len(cases))
    A_case = c["fit"] * (W_CASE["semantic"] * c["sem"] + W_CASE["concept"] * c["concept"] + W_CASE["llm"] * llm)
    A_snip = s["fit"] * (W_SNIP["semantic"] * s["sem"] + W_SNIP["concept"] * s["concept"])
    w = np.array([r.weight for r in roots])
    case_score = w @ A_case if len(roots) else np.zeros(len(cases))
    snip_score = w @ A_snip if len(roots) else np.zeros(len(snips))
    fitc = lambda m: np.broadcast_to(m, A_case.shape).tolist()
    rows = [r.hypothesis.id for r in roots]

    top_c = [j for j in np.argsort(-case_score) if c["fit"][j] == 1][:N_TOP_CASES]
    top_s = [j for j in np.argsort(-snip_score) if s["fit"][j] == 1][:N_TOP_SNIPPETS]
    mx = float(case_score.max()) if len(case_score) and case_score.max() > 0 else 1.0

    all_rc = set().union(*[rc_concepts(r) for r in roots]) if roots else set()
    fns = sorted([f for f in a["field_notes"] if set(f.concepts) & all_rc],
                 key=lambda f: -jaccard(set(f.concepts), all_rc))[:N_FIELD_NOTES]
    return {
        "case_alignment": Alignment(row_ids=rows, col_ids=[d.id for d in cases], values=A_case.tolist(),
                                    components={"semantic": c["sem"].tolist(), "concept": c["concept"].tolist(),
                                                "llm": llm.tolist(), "fit": fitc(c["fit"])}),
        "snippet_alignment": Alignment(row_ids=rows, col_ids=[d.id for d in snips], values=A_snip.tolist(),
                                       components={"semantic": s["sem"].tolist(), "concept": s["concept"].tolist(),
                                                   "fit": np.broadcast_to(s["fit"], A_snip.shape).tolist()}),
        "top_cases": [{"id": cases[j].id, "name": cases[j].name, "score": float(case_score[j]),
                       "measured_roi_text": cases[j].measured_roi_text, "kpi_deltas": cases[j].kpi_deltas} for j in top_c],
        "top_snippets": [{"id": snips[j].id, "source": snips[j].source, "finding": snips[j].finding,
                          "score": float(snip_score[j])} for j in top_s],
        "field_notes": [{"id": f.id, "title": f.title, "text": f.text} for f in fns],
        "case_score_norm": {cases[j].id: float(case_score[j]) / mx for j in range(len(cases))},
        "excluded_cases": [cases[j].id for j in range(len(cases)) if c["fit"][j] == 0],
        "excluded_snippets": [snips[j].id for j in range(len(snips)) if s["fit"][j] == 0],
    }
