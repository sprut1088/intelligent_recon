from dataclasses import dataclass
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / '.env')

ROOT_DIR = Path(__file__).resolve().parents[1]
SAMPLE_DATA_DIR = ROOT_DIR / "sample_data"
RUNTIME_DATA_DIR = ROOT_DIR / "runtime_data"
RUNTIME_DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = RUNTIME_DATA_DIR / "recon.db"

@dataclass(frozen=True)
class Settings:
    app_name: str = "Intelligent Recon Engine"
    app_version: str = "0.1.0"
    database_path: Path = DB_PATH
    runtime_data_dir: Path = RUNTIME_DATA_DIR
    sample_data_dir: Path = SAMPLE_DATA_DIR
    psr_sample_path: Path = SAMPLE_DATA_DIR / "psr_10000_payments.txt"
    camt_sample_path: Path = SAMPLE_DATA_DIR / "camt_10000_payments.xml"
    report_sample_path: Path = SAMPLE_DATA_DIR / "reconciliation_detailed_report.csv"
    psr_amount_divisor: float = float(os.getenv("PSR_AMOUNT_DIVISOR", "1"))
    exact_amount_tolerance: float = float(os.getenv("EXACT_AMOUNT_TOLERANCE", "0.0001"))
    minor_variance_tolerance: float = float(os.getenv("MINOR_VARIANCE_TOLERANCE", "50"))
    ai_candidate_variance_pct: float = float(os.getenv("AI_CANDIDATE_VARIANCE_PCT", "0.25"))
    auto_close_confidence: int = int(os.getenv("AUTO_CLOSE_CONFIDENCE", "95"))
    assisted_confidence: int = int(os.getenv("ASSISTED_CONFIDENCE", "80"))
    learning_min_support: int = int(os.getenv("LEARNING_MIN_SUPPORT", "3"))
    in_transit_days: int = int(os.getenv("IN_TRANSIT_DAYS", "3"))
    # LLM provider: "openrouter" (default) or "anthropic"
    llm_provider: str = os.getenv("LLM_PROVIDER", "openrouter")
    # Model name — use provider-specific format:
    #   openrouter:  "openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet"
    #   anthropic:   "claude-3-5-sonnet-latest"
    llm_model: str = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")
    llm_max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "300"))

settings = Settings()
