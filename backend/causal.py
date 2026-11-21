"""Influence matrix and DEMATEL (§6.9)."""
import numpy as np
from .schemas import CausalEdge


def influence_matrix(ids: list[str], edges: list[CausalEdge]) -> np.ndarray:
    idx = {h: i for i, h in enumerate(ids)}
    W = np.zeros((len(ids), len(ids)))
    for e in edges:
        if e.source in idx and e.target in idx and e.source != e.target:
            W[idx[e.source], idx[e.target]] = max(W[idx[e.source], idx[e.target]], e.strength / 3.0)
    return W


def dematel(W: np.ndarray):
    n = len(W)
    s = max(W.sum(axis=1).max(initial=0), W.sum(axis=0).max(initial=0))
    if s == 0:
        z = np.zeros(n)
        return z, z, np.ones(n), z
    N = W / s
    T = N @ np.linalg.inv(np.eye(n) - N)
    r, c = T.sum(axis=1), T.sum(axis=0)
    return r, c, r + c, r - c


def root_cause_flags(prominence, relation) -> tuple[list[bool], list[float]]:
    n = len(relation)
    if n == 0:
        return [], []
    roots = [bool(x > 0) for x in relation]
    if not any(roots):
        if np.allclose(relation, 0) and np.allclose(prominence, 1):   # no edges: all independent roots
            roots = [True] * n
        else:
            roots[int(np.argmax(relation))] = True
    total = sum(p for p, r in zip(prominence, roots) if r)
    weights = [(p / total if total > 0 else 1 / sum(roots)) if r else 0.0 for p, r in zip(prominence, roots)]
    return roots, weights
