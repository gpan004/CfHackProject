"""Typed knowledge graph (v2).

Two layers:
- the REFERENCE graph, built once from hr_knowledge.json + the dataset + data/kg_facts.json (never mutated);
- a CLIENT layer per run: a copy of the reference graph plus the client's observations (metrics, requests, segments).

Every edge carries where it comes from (`origin`) and, when it comes from a document, the verbatim quote (`evidence`).
"""
import json
import re
from functools import lru_cache

import networkx as nx

from ..config import DATA_DIR
from ..ingest import track_a, sandbox
from ..knowledge import K, CATALOG, CONCEPTS, ALL_ARCHETYPES, tag_concepts

FACTS_FILE = DATA_DIR / "kg_facts.json"
PILLAR_OF_SECTION = {"public_reputation": "branding", "career_portal_and_funnel": "recruiting",
                     "social_and_employee_voice": "advocacy", "hiring_and_retention_kpis": "retention"}


class FactError(Exception):
    pass


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


@lru_cache
def facts() -> dict:
    return json.loads(FACTS_FILE.read_text(encoding="utf-8"))


@lru_cache
def documents() -> dict[str, dict]:
    """Every citable reference document: id -> {kind, title, text}."""
    a = track_a()
    docs = {}
    for f in a["field_notes"]:
        docs[f.id] = {"kind": "field_note", "title": f.title, "text": f.text}
    for s in a["snippets"]:
        docs[s.id] = {"kind": "snippet", "title": s.source, "text": s.finding}
    for c in a["cases"]:
        docs[c.id] = {"kind": "case", "title": c.name, "text": c.problem + " " + c.measured_roi_text}
    return docs


def quote_in_doc(doc_id: str, quote: str) -> bool:
    d = documents().get(doc_id)
    return d is not None and bool(norm(quote)) and norm(quote) in norm(d["text"])


def validate_facts() -> list[str]:
    """Returns a list of problems; empty means every fact is backed by a verbatim quote and valid ids."""
    F, errs = facts(), []
    metric_keys = set(F["glossary"]["metrics"])

    def ev_ok(where, evs):
        if not evs:
            errs.append(f"{where}: no evidence")
        for e in evs:
            if not quote_in_doc(e["source"], e["quote"]):
                errs.append(f"{where}: quote not found verbatim in {e['source']}: {e['quote'][:80]!r}")

    for c in F["causes"]:
        for x in (c["from"], c["to"]):
            if x not in CONCEPTS:
                errs.append(f"{c['id']}: unknown problem {x}")
        ev_ok(c["id"], c["evidence"])
    for c in F["conditions"]:
        for x in c["closed_by"]:
            if x not in CONCEPTS:
                errs.append(f"{c['id']}: unknown problem {x}")
        ev_ok(c["id"], c["evidence"])
    for e in F["effects"]:
        for a in e["actions"]:
            if a not in CATALOG:
                errs.append(f"{e['id']}: unknown action {a}")
        if e["metric"] and e["metric"] not in metric_keys:
            errs.append(f"{e['id']}: unknown metric {e['metric']}")
        ev_ok(e["id"], e["evidence"])
    for t in F["thresholds"]:
        if t["problem"] not in CONCEPTS or t["metric"] not in metric_keys:
            errs.append(f"{t['id']}: unknown problem or metric")
        ev_ok(t["id"], t["evidence"])
    for p, ms in F["indicators"].items():
        if p not in CONCEPTS:
            errs.append(f"indicators: unknown problem {p}")
        errs += [f"indicators.{p}: unknown metric {m}" for m in ms if m not in metric_keys]
    errs += [f"glossary: problem {c} missing" for c in CONCEPTS if c not in F["glossary"]["problems"]]
    errs += [f"glossary: action {a} missing" for a in CATALOG if a not in F["glossary"]["actions"]]
    return errs


def _ev(evs: list[dict]) -> list[dict]:
    return [{"kind": "document", "ref": e["source"], "quote": e["quote"]} for e in evs]


CATALOG_EV = [{"kind": "catalog", "ref": "hr_knowledge.json", "quote": ""}]


@lru_cache
def reference_graph() -> nx.MultiDiGraph:
    errs = validate_facts()
    if errs:
        raise FactError("kg_facts.json is not fully evidence-backed:\n  " + "\n  ".join(errs))
    F, A, G = facts(), track_a(), nx.MultiDiGraph()
    gl = F["glossary"]

    def edge(u, v, rel, origin, evidence, **kw):
        G.add_edge(u, v, key=f"{rel}:{kw.get('fact', '')}", rel=rel, origin=origin, evidence=evidence, **kw)

    for pid in ("branding", "recruiting", "advocacy", "retention", "cross"):
        G.add_node(pid, kind="pillar", label=pid.capitalize())
    for a in ALL_ARCHETYPES:
        G.add_node(a, kind="worker", label=a.replace("_", " "))
    for key, (label, unit) in gl["metrics"].items():
        G.add_node(key, kind="metric", label=label, unit=unit)
    for c in K["concepts"]:
        label, plain = gl["problems"][c["id"]]
        G.add_node(c["id"], kind="problem", label=label, plain=plain, pillar=c["pillar"],
                   scope=c["archetype_scope"], polarity="asset" if c["id"] in F["assets"] else "problem")
        edge(c["id"], c["pillar"], "in_pillar", "catalog", CATALOG_EV)
        for m in F["indicators"].get(c["id"], []):
            edge(c["id"], m, "indicated_by", "analyst_mapping", [{"kind": "analyst_mapping", "ref": "kg_facts.json", "quote": ""}])
    for i in K["interventions"]:
        G.add_node(i["id"], kind="action", label=i["name"], plain=gl["actions"][i["id"]], type=i["type"],
                   pillar=i["pillar"], requires_readiness=i["requires_readiness"])
        edge(i["id"], i["pillar"], "in_pillar", "catalog", CATALOG_EV)
        for c in i["fixes_concepts"]:
            edge(i["id"], c, "fixes", "catalog", CATALOG_EV)
        for m in i["target_metrics"]:
            if m in G:
                edge(i["id"], m, "changes", "catalog", CATALOG_EV)
        for p in i["prerequisites_any"]:
            edge(i["id"], p, "needs_first", "catalog", CATALOG_EV, group="any_of")
        for w in (ALL_ARCHETYPES if i["allowed_archetypes"] == "all" else i["allowed_archetypes"]):
            edge(i["id"], w, "fits", "catalog", CATALOG_EV)
    for c in F["conditions"]:
        G.add_node(c["id"], kind="condition", label=c["label"], plain=c["plain"], evidence=_ev(c["evidence"]))
        for p in c["closed_by"]:
            edge(p, c["id"], "closes", "reference", _ev(c["evidence"]), fact=c["id"])
        for i in K["interventions"]:
            if i["requires_readiness"]:
                edge(i["id"], c["id"], "blocked_by", "catalog", _ev(c["evidence"]), fact=c["id"])
    for c in F["causes"]:
        edge(c["from"], c["to"], "causes", "reference", _ev(c["evidence"]), fact=c["id"],
             strength=c["strength"], mechanism=c["mechanism"], scope=c.get("scope", "all"))
    for e in F["effects"]:
        for a in e["actions"]:
            target = e["metric"] or e["evidence"][0]["source"]
            edge(a, target, "effect_on", "reference", _ev(e["evidence"]), fact=e["id"], low=e["low"], high=e["high"],
                 unit=e["unit"], scope=e.get("scope", "all"))
    for t in F["thresholds"]:
        src = t["evidence"][0]["source"]
        edge(src, t["metric"], "threshold_for", "reference", _ev(t["evidence"]), fact=t["id"], op=t["op"],
             value=t["value"], problem=t["problem"], meaning=t["meaning"], scope=t.get("scope", "all"))
    for c in A["cases"]:
        G.add_node(c.id, kind="case", label=c.name, sector=c.sector_profile, outcome=c.measured_roi_text)
        for p in tag_concepts(c.problem):       # only problems named in the challenge text, not inferred from actions
            edge(c.id, p, "had_problem", "reference", [{"kind": "document", "ref": c.id, "quote": c.problem}])
        for s in c.interventions:
            for a in s.intervention_ids:
                edge(c.id, a, "used", "reference", [{"kind": "document", "ref": c.id, "quote": s.text}], step=s.step)
        for w in c.archetypes:
            edge(c.id, w, "workers", "reference", [{"kind": "document", "ref": c.id, "quote": c.sector_profile}])
        for m, d in c.kpi_deltas.items():
            if m in G:
                edge(c.id, m, "changed", "reference", [{"kind": "document", "ref": c.id, "quote": c.measured_roi_text}], delta=d)
    for s in A["snippets"]:
        G.add_node(s.id, kind="snippet", label=s.source, text=s.finding)
        for p in s.concepts:
            edge(s.id, p, "mentions", "reference", [{"kind": "document", "ref": s.id, "quote": s.finding}])
        for w in s.archetypes:
            edge(s.id, w, "scope", "reference", [{"kind": "document", "ref": s.id, "quote": s.finding}])
    for f in A["field_notes"]:
        G.add_node(f.id, kind="field_note", label=f.title, text=f.text)
        for p in f.concepts:
            edge(f.id, p, "mentions", "reference", [{"kind": "document", "ref": f.id, "quote": f.text}])
    G.graph["version"] = F["version"]
    return G


# ---------- queries ----------
def out_edges(G, node, rel):
    return [(v, d) for _, v, d in G.out_edges(node, data=True) if d["rel"] == rel]


def in_edges(G, node, rel):
    return [(u, d) for u, _, d in G.in_edges(node, data=True) if d["rel"] == rel]


def label(G, node) -> str:
    return G.nodes[node].get("label", node) if node in G else node


def kind_nodes(G, kind) -> list[str]:
    return sorted(n for n, d in G.nodes(data=True) if d.get("kind") == kind)


def graph_stats(G) -> dict:
    kinds, rels = {}, {}
    for _, d in G.nodes(data=True):
        kinds[d.get("kind")] = kinds.get(d.get("kind"), 0) + 1
    for _, _, d in G.edges(data=True):
        rels[d["rel"]] = rels.get(d["rel"], 0) + 1
    return {"nodes": kinds, "edges": rels}


# ---------- client layer ----------
def client_layer(client) -> nx.MultiDiGraph:
    """A per-run copy of the reference graph with the client's observations attached. The reference graph is untouched."""
    G = reference_graph().copy()
    G.add_node("client", kind="client", label=client.company_name, archetypes=client.archetypes,
               gate_open=client.readiness.gate_open)
    for w in client.archetypes:
        G.add_edge("client", w, key="workforce", rel="workforce", origin="client_data", evidence=[])
    for k, r in client.metrics.items():
        if k not in G:
            G.add_node(k, kind="metric", label=k, unit="")
        G.nodes[k].update(value=r.value, peer=r.peer, status=r.status)
    for rid in client.leadership_requests:
        n = f"request:{rid}"
        G.add_node(n, kind="request", label=f"Leadership request: {label(G, rid)}")
        G.add_edge(n, rid, key="requests", rel="requests", origin="client_text",
                   evidence=[{"kind": "client_text", "ref": "internal.leadership_perceptions_and_requests",
                              "quote": client.internal.get("leadership_perceptions_and_requests", "")}])
    for s in client.segments:
        G.add_node(f"segment:{s.name}", kind="segment", label=s.name.replace("_", " "), rating=s.rating, flag=s.flag)
    return G
