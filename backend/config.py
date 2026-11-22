import os
from pathlib import Path
from dotenv import load_dotenv

try:  # use the operating system's certificate store (antivirus HTTPS scanning, e.g. Norton, re-signs traffic)
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
RUNS_DIR = ROOT / "runs"
CACHE_DIR = ROOT / "cache"
SANDBOX_FILE = DATA_DIR / "ingaze_sandbox_dataset.json"
SNAPSHOT_FILE = DATA_DIR / "ingaze_synthetic_analytics_snapshots.json"
KNOWLEDGE_FILE = DATA_DIR / "hr_knowledge.json"
ASSUMPTIONS_FILE = DATA_DIR / "assumptions.json"

LOCAL_LLM_BASE_URL = os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "mistral-nemo")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODELS = [m.strip() for m in os.getenv("OPENROUTER_MODELS", "").split(",") if m.strip()]
LLM_CACHE = os.getenv("LLM_CACHE", "1") == "1"
LOCAL_TIMEOUT = 180
REMOTE_TIMEOUT = 90
EMBED_MODEL = "intfloat/multilingual-e5-small"

STATUS_TOL = 0.10
SAY_DO_GAP_STARS = 1.1
SEGMENT_WEAK_DELTA = 0.5
SEGMENT_STRONG_REL = 0.10
W_CASE = dict(semantic=0.4, concept=0.3, llm=0.3)
W_SNIP = dict(semantic=0.6, concept=0.4)
TOP_K_LLM_VERIFY = 5
N_CANDIDATE_PLANS = 5
N_JURY_PLANS = 3
W_PRE = dict(coverage=0.6, evidence=0.4)
W_FINAL = dict(jury=0.5, coverage=0.3, evidence=0.2)
PENALTY_PER_FIX = 0.05
PENALTY_CAP = 0.30
N_TOP_CASES = 3
N_TOP_SNIPPETS = 4
N_FIELD_NOTES = 3
PILLAR_IDS = ["branding", "recruiting", "advocacy", "retention"]
KPI_PROJECTION_KEYS = ["early_first_year_attrition_pct", "avg_time_to_hire_days", "application_form_dropoff_pct",
                       "applicant_conversion_rate_pct", "external_claims_gap_stars_5", "corporate_linkedin_er_pct",
                       "manual_hr_tracking_hours_month", "overall_review_rating_5"]

JURY_PERSONAS = ["Board Member", "HR Manager", "CFO", "Employee in the affected cohort",
                 "Potential Candidate from the target workforce"]
PERSONA_DESCRIPTIONS = {
    "Board Member": "Cares about strategic coherence and reputational risk.",
    "HR Manager": "Cares about the execution capacity of a small HR team.",
    "CFO": "Cares about auditability, spend discipline and measurable payback.",
    "Employee in the affected cohort": "Cares about credibility and day-to-day impact.",
    "Potential Candidate from the target workforce": "Cares about attractiveness from the outside.",
}

TEAM_NAME = "Ingaze Engine"
CHOSEN_ARCHITECTURE_PARADIGM = (
    "Dual-track neuro-symbolic pipeline: deterministic normalization + catalog guardrails + DEMATEL causal matrix "
    "+ hybrid case matching; local 12B agents for pillar analysis, confutation, matching and jury; "
    "OpenRouter for hypotheses, causal mapping and strategy")
