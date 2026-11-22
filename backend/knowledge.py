import json
import re
import networkx as nx

from .config import KNOWLEDGE_FILE, ASSUMPTIONS_FILE

K = json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))
ASSUMPTIONS = json.loads(ASSUMPTIONS_FILE.read_text(encoding="utf-8"))
CATALOG = {i["id"]: i for i in K["interventions"]}
CONCEPTS = {c["id"]: c for c in K["concepts"]}
RULES = K["metric_rules"]
LOWER_IS_BETTER = set(RULES["lower_is_better"])
NEUTRAL = set(RULES["neutral"])
ALIASES = RULES["aliases"]
ALL_ARCHETYPES = list(K["archetypes"])

_ARCH_RE = {a: [re.compile(r"\b" + re.escape(kw), re.I) for kw in kws] for a, kws in K["archetypes"].items()}


def tag_archetypes(text: str) -> list[str]:
    return [a for a, pats in _ARCH_RE.items() if any(p.search(text or "") for p in pats)]


def tag_concepts(text: str) -> list[str]:
    t = (text or "").lower()
    return [c["id"] for c in K["concepts"] if any(s in t for s in c["synonyms"])]


def tag_interventions(text: str) -> list[str]:
    """Catalog ids whose synonyms appear in text, ordered by first appearance."""
    t = (text or "").lower()
    hits = []
    for i in K["interventions"]:
        pos = [t.find(s) for s in i["synonyms"] if s in t]
        if pos:
            hits.append((min(pos), i["id"]))
    return [i for _, i in sorted(hits)]


def allowed(scope, client_arch: list[str]) -> bool:
    return scope == "all" or bool(set(scope) & set(client_arch))


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if (a or b) else 0.0


def build_graph(cases, snippets, field_notes) -> nx.Graph:
    g = nx.Graph()
    for a in ALL_ARCHETYPES:
        g.add_node(a, kind="archetype")
    for c in K["concepts"]:
        g.add_node(c["id"], kind="concept")
    for i in K["interventions"]:
        g.add_node(i["id"], kind="intervention")
        for c in i["fixes_concepts"]:
            g.add_edge(i["id"], c)
        for a in (ALL_ARCHETYPES if i["allowed_archetypes"] == "all" else i["allowed_archetypes"]):
            g.add_edge(i["id"], a)
    for c in cases:
        g.add_node(c.id, kind="case")
        for x in c.problem_concepts + c.intervention_ids + c.archetypes:
            g.add_edge(c.id, x)
    for s in snippets:
        g.add_node(s.id, kind="snippet")
        for x in s.concepts + s.archetypes:
            g.add_edge(s.id, x)
    for f in field_notes:
        g.add_node(f.id, kind="field_note")
        for x in f.concepts:
            g.add_edge(f.id, x)
    return g


def concepts_of(g: nx.Graph, node_id: str) -> set[str]:
    if node_id not in g:
        return set()
    return {n for n in g.neighbors(node_id) if g.nodes[n].get("kind") == "concept"}
