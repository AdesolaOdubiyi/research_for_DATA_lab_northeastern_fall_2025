"""Load tunables from repo-root ``config.yaml`` into module-level constants."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent

OUTPUT_DIR: Path = ROOT_DIR / "outputs"
RESULTS_DB_PATH: Path = OUTPUT_DIR / "results.db"
AUDIT_DB_PATH: Path = OUTPUT_DIR / "audit.db"
USE_WAL: bool = True
CHECKPOINT_FREQUENCY: int = 50
JSONL_PATH: Path = ROOT_DIR / "data" / "sample" / "shows.jsonl"
MATCHED_CSV_PATH: Path = OUTPUT_DIR / "matched_results.csv"
MATCHED_JSON_PATH: Path = OUTPUT_DIR / "matched_results.json"
STATS_SUMMARY_PATH: Path = OUTPUT_DIR / "stats_summary.json"
LOG_LEVEL: str = "INFO"

IMDB_BASE_DELAY: float = 1.3
IMDB_REQUEST_TIMEOUT: int = 10
IMDB_MAX_RETRIES: int = 3

SHOW_SIMILARITY_THRESHOLD: int = 90
PARENT_SIMILARITY_THRESHOLD: int = 85
EPISODE_FUZZY_HIGH: int = 95
EPISODE_FUZZY_MEDIUM: int = 85
DATE_TOLERANCE_DAYS: int = 2

OFFLINE_VENDOR_FIXTURE_PATH: Path = ROOT_DIR / "data" / "sample" / "offline_vendor.json"


def apply_yaml(raw: Dict[str, Any]) -> None:
    """Populate module globals from parsed YAML."""
    global OUTPUT_DIR, RESULTS_DB_PATH, AUDIT_DB_PATH, USE_WAL, CHECKPOINT_FREQUENCY
    global MATCHED_CSV_PATH, MATCHED_JSON_PATH, STATS_SUMMARY_PATH, LOG_LEVEL
    global IMDB_BASE_DELAY, IMDB_REQUEST_TIMEOUT, IMDB_MAX_RETRIES
    global SHOW_SIMILARITY_THRESHOLD, PARENT_SIMILARITY_THRESHOLD
    global EPISODE_FUZZY_HIGH, EPISODE_FUZZY_MEDIUM, DATE_TOLERANCE_DAYS
    global OFFLINE_VENDOR_FIXTURE_PATH, JSONL_PATH

    paths = raw.get("paths", {})
    sqlite = raw.get("sqlite", {})
    ck = raw.get("checkpointing", {})
    scrap = raw.get("scraping", {})
    match = raw.get("matching", {})
    log = raw.get("logging", {})

    OUTPUT_DIR = ROOT_DIR / paths.get("output_dir", "outputs")
    RESULTS_DB_PATH = ROOT_DIR / paths.get("results_db", "outputs/results.db")
    AUDIT_DB_PATH = ROOT_DIR / paths.get("audit_db", "outputs/audit.db")
    MATCHED_CSV_PATH = ROOT_DIR / paths.get("matched_csv", "outputs/matched_results.csv")
    MATCHED_JSON_PATH = ROOT_DIR / paths.get("matched_json", "outputs/matched_results.json")
    STATS_SUMMARY_PATH = ROOT_DIR / paths.get("stats_json", "outputs/stats_summary.json")

    USE_WAL = bool(sqlite.get("use_wal", True))
    CHECKPOINT_FREQUENCY = int(ck.get("frequency_shows", 50))

    IMDB_BASE_DELAY = float(scrap.get("base_delay_seconds", 1.3))
    IMDB_REQUEST_TIMEOUT = int(scrap.get("request_timeout_seconds", 10))
    IMDB_MAX_RETRIES = int(scrap.get("max_retries", 3))

    SHOW_SIMILARITY_THRESHOLD = int(match.get("show_similarity_threshold_percent", 90))
    PARENT_SIMILARITY_THRESHOLD = int(match.get("parent_similarity_threshold_percent", 85))
    EPISODE_FUZZY_HIGH = int(match.get("episode_fuzzy_high_percent", 95))
    EPISODE_FUZZY_MEDIUM = int(match.get("episode_fuzzy_medium_percent", 85))
    DATE_TOLERANCE_DAYS = int(match.get("date_tolerance_days", 2))

    LOG_LEVEL = str(log.get("level", "INFO"))

    OFFLINE_VENDOR_FIXTURE_PATH = ROOT_DIR / paths.get(
        "offline_vendor_fixture", "data/sample/offline_vendor.json"
    )
    JSONL_PATH = ROOT_DIR / paths.get("input_jsonl", "data/sample/shows.jsonl")


def load_config(path: Optional[Path] = None) -> None:
    """Load ``config.yaml`` from repo root (or ``path``)."""
    cfg_path = path or (ROOT_DIR / "config.yaml")
    with cfg_path.open(encoding="utf-8") as handle:
        apply_yaml(yaml.safe_load(handle))
