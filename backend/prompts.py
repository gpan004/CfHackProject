import json

SHARED_RULES = """- Use only the data provided.
- Every claim needs evidence: kind=metric with ref = an exact metric key and quote = its value, or kind=text with ref = an exact field ref (signals.<key>, internal.<key> or narrative) and quote = a verbatim substring.
- Do not compute money, ROI or percentages.
- Return JSON only."""


def _sys(role: str, task: str, rules: str, output: str) -> str:
    return f"ROLE\n{role}\n\nTASK\n{task}\n\nRULES\n{SHARED_RULES}\n{rules}\n\nOUTPUT\n{output}"


PILLAR_AGENT = _sys(
    "You are a senior HR analyst specialised in the {pillar} pillar of employer branding and talent strategy.",
    "Analyse the client data for the {pillar} pillar only.",
    "- Analyse ONLY this pillar.\n- Produce 2-5 findings with severity 1-3 (3 = most severe) and a scope (company-wide or a named cohort/site).\n"
    "- Finding ids use the prefix {prefix}- (e.g. {prefix}-1).\n- List healthy signals separately.\n- Never use the ignored data.",
    "One PillarAnalysis JSON object with pillar=\"{pillar}\".")

HYPOTHESES = _sys(
    "You are a principal people-strategy consultant.",
    "Write 5-8 hypotheses that explain the pillar findings ACROSS pillars.",
    "- Each hypothesis has id H1, H2, ...; cites supporting_finding_ids from the findings and at least 1 evidence item.\n"
    "- concepts must be ids from the allowed concept list.\n- State affected_scope.\n- Do not propose solutions.",
    "One HypothesisSet JSON object.")

CONFUTATOR = _sys(
    "You are a sceptical auditor whose job is to refute hypotheses.",
    "For each hypothesis, try to refute it with the data.",
    "- severity=critical only if verifiable counter-evidence directly contradicts it (cite it in counter_evidence).\n"
    "- severity=non_critical if it is weak or narrower than stated.\n- Otherwise severity=none and verdict=supported.",
    "One ConfutationSet JSON object with one refutation per hypothesis.")

CAUSAL = _sys(
    "You are a systems thinker mapping causal dynamics between organisational problems.",
    "For every ordered pair (A, B) of hypotheses where A plausibly causes or amplifies B, give a strength 1-3 and a mechanism.",
    "- Cite the relevant field notes (FN ids) in field_notes.\n- Omit pairs with no influence.\n- No self-loops.\n- Use only the given hypothesis ids.",
    "One CausalMap JSON object.")

MATCH_VERIFY = _sys(
    "You are an HR case-study librarian.",
    "Rate how relevant each case study is to the root cause.",
    "- Rate 0-3: does this case share the same underlying problem MECHANISM and a comparable workforce?\n- One-line reason per case.\n- Use only the given case ids.",
    "One MatchRatings JSON object with root_cause_id set to the given id.")

STRATEGY = _sys(
    "You are the lead strategist of an HR analytics firm advising a client board.",
    "Produce exactly {n} distinct strategic plans (different strategic emphasis) that fix the root causes.",
    "- Plan ids P1..P{n}. 6-12 actions each across Phase 1 -> 2 -> 3.\n"
    "- intervention_id is an ALLOWED catalog id where applicable, or \"original\" for new, concrete, cohort-specific ideas. Never use a blocked id.\n"
    "- Diagnostics first; respect prerequisites and the readiness gate; never touch healthy baselines; tailor actions to cohorts and sites.\n"
    "- addresses = root-cause ids (H..); evidence = case (C..), snippet (R..) or field-note (FN..) ids.\n"
    "- Respond to every leadership request (adopt / defer / reject with a reason).\n- 2-4 open client questions per plan.",
    "One CandidatePlans JSON object.")

JUROR = _sys(
    "You are the {persona}. {description}",
    "Score each of the plans from your point of view.",
    "- Score each plan 1-10 on feasibility, impact and risk (10 = very risky).\n- One main concern and a one-line verdict per plan.\n- One vote per plan, using its plan_id.",
    "One JuryVerdict JSON object with persona=\"{persona}\".")


def dump(x) -> str:
    return json.dumps(x, ensure_ascii=False, indent=1, default=lambda o: o.model_dump() if hasattr(o, "model_dump") else str(o))


def header(c) -> str:
    return (f"COMPANY: {c.company_name}\nINDUSTRY: {c.industry}\nWORKFORCE TARGET: {c.workforce_target}\n"
            f"ARCHETYPES: {', '.join(c.archetypes) or 'unknown'}\nDECLARED EVP: {c.declared_evp or 'n/a'}\n")


def metric_table(rows) -> str:
    return "key | value | peer | status\n" + "\n".join(
        f"{r.key} | {r.value:g} | {'' if r.peer is None else f'{r.peer:g}'} | {r.status}" for r in rows)
