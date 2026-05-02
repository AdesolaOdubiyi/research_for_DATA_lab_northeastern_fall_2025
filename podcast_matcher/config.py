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

HTTP_BASE_DELAY: float = 1.3
HTTP_REQUEST_TIMEOUT: int = 10
HTTP_MAX_RETRIES: int = 3

SHOW_SIMILARITY_THRESHOLD: int = 90
PARENT_SIMILARITY_THRESHOLD: int = 85
EPISODE_FUZZY_HIGH: int = 95
EPISODE_FUZZY_MEDIUM: int = 85
DATE_TOLERANCE_DAYS: int = 2

SHOW_VALIDATION_MAX_RECURSION_DEPTH: int = 3
SHOW_VALIDATION_REJECT_SERIES_YEAR_AFTER: int = 2020
SHOW_VALIDATION_KEYWORD_COVERAGE_MINIMUM: float = 0.7
SHOW_VALIDATION_COVERAGE_FALLBACK_SIMILARITY_PERCENT: int = 95
SHOW_VALIDATION_EXPLICIT_PODCAST_PAGE_SCORE: int = 10
SHOW_VALIDATION_PODCAST_LIKE_PASS_MINIMUM: int = 3
SHOW_VALIDATION_LARGE_CAST_MINIMUM_LINKS: int = 5
SHOW_VALIDATION_LARGE_CAST_PENALTY: int = 2
SHOW_VALIDATION_GENRE_KEYWORD_BOOST: int = 1
SHOW_VALIDATION_RISK_HIGH_BELOW_SCORE: int = 3
SHOW_VALIDATION_RISK_MEDIUM_BELOW_SCORE: int = 10
SHOW_VALIDATION_REJECT_BELOW_PODCAST_SCORE: int = 0
SHOW_VALIDATION_SCORE_DESCRIPTION_PODCAST: int = 3
SHOW_VALIDATION_SCORE_DESCRIPTION_EPISODE: int = 2
SHOW_VALIDATION_SCORE_DESCRIPTION_HOSTED: int = 2
SHOW_VALIDATION_SCORE_DESCRIPTION_WEEKLY_DAILY: int = 1
SHOW_VALIDATION_SCORE_DESCRIPTION_GUESTS: int = 1

OFFLINE_CATALOG_SAMPLE_PATH: Path = ROOT_DIR / "data" / "sample" / "offline_vendor.json"

CB_MAX_CONSECUTIVE_503S: int = 25
CB_MAX_CONSECUTIVE_NETWORK_ERRORS: int = 10
CB_EARLY_WARNING_503S: int = 15
CB_PAUSE_SECONDS: int = 1800

_CONFIG_LOADED: bool = False
_CONFIG_SOURCE_PATH: Optional[Path] = None


def _apply_path_settings(paths: Dict[str, Any]) -> None:
    module_globals = globals()

    module_globals["OUTPUT_DIR"] = ROOT_DIR / paths.get("output_dir", "outputs")
    module_globals["RESULTS_DB_PATH"] = ROOT_DIR / paths.get("results_db", "outputs/results.db")
    module_globals["AUDIT_DB_PATH"] = ROOT_DIR / paths.get("audit_db", "outputs/audit.db")
    module_globals["MATCHED_CSV_PATH"] = ROOT_DIR / paths.get("matched_csv", "outputs/matched_results.csv")
    module_globals["MATCHED_JSON_PATH"] = ROOT_DIR / paths.get("matched_json", "outputs/matched_results.json")
    module_globals["STATS_SUMMARY_PATH"] = ROOT_DIR / paths.get("stats_json", "outputs/stats_summary.json")

    offline_sample_rel = paths.get("offline_catalog_sample") or paths.get(
        "offline_vendor_fixture", "data/sample/offline_vendor.json"
    )
    module_globals["OFFLINE_CATALOG_SAMPLE_PATH"] = ROOT_DIR / offline_sample_rel
    module_globals["JSONL_PATH"] = ROOT_DIR / paths.get("input_jsonl", "data/sample/shows.jsonl")


def _apply_sqlite_and_checkpoint(sqlite: Dict[str, Any], checkpointing_raw: Dict[str, Any]) -> None:
    module_globals = globals()

    module_globals["USE_WAL"] = bool(sqlite.get("use_wal", True))
    module_globals["CHECKPOINT_FREQUENCY"] = int(checkpointing_raw.get("frequency_shows", 50))


def _apply_http_client_settings(http_client: Dict[str, Any]) -> None:
    module_globals = globals()

    module_globals["HTTP_BASE_DELAY"] = float(http_client.get("base_delay_seconds", 1.3))
    module_globals["HTTP_REQUEST_TIMEOUT"] = int(http_client.get("request_timeout_seconds", 10))
    module_globals["HTTP_MAX_RETRIES"] = int(http_client.get("max_retries", 3))


def _apply_circuit_breaker_settings(circuit_breaker_raw: Dict[str, Any]) -> None:
    module_globals = globals()

    module_globals["CB_MAX_CONSECUTIVE_503S"] = int(circuit_breaker_raw.get("max_consecutive_503s", 25))
    module_globals["CB_MAX_CONSECUTIVE_NETWORK_ERRORS"] = int(
        circuit_breaker_raw.get("max_consecutive_network_errors", 10)
    )
    module_globals["CB_EARLY_WARNING_503S"] = int(circuit_breaker_raw.get("early_warning_threshold", 15))
    module_globals["CB_PAUSE_SECONDS"] = int(circuit_breaker_raw.get("pause_duration_seconds", 1800))


def _apply_matching_settings(matching_config: Dict[str, Any]) -> None:
    module_globals = globals()

    module_globals["SHOW_SIMILARITY_THRESHOLD"] = int(matching_config.get("show_similarity_threshold_percent", 90))
    module_globals["PARENT_SIMILARITY_THRESHOLD"] = int(matching_config.get("parent_similarity_threshold_percent", 85))
    module_globals["EPISODE_FUZZY_HIGH"] = int(matching_config.get("episode_fuzzy_high_percent", 95))
    module_globals["EPISODE_FUZZY_MEDIUM"] = int(matching_config.get("episode_fuzzy_medium_percent", 85))
    module_globals["DATE_TOLERANCE_DAYS"] = int(matching_config.get("date_tolerance_days", 2))


def _apply_show_validation_settings(
    show_val: Dict[str, Any], scoring: Dict[str, Any]
) -> None:
    module_globals = globals()

    module_globals["SHOW_VALIDATION_MAX_RECURSION_DEPTH"] = int(show_val.get("max_recursion_depth", 3))
    module_globals["SHOW_VALIDATION_REJECT_SERIES_YEAR_AFTER"] = int(
        show_val.get("reject_catalog_series_start_year_after", 2020)
    )
    module_globals["SHOW_VALIDATION_KEYWORD_COVERAGE_MINIMUM"] = float(show_val.get("keyword_coverage_minimum", 0.7))
    module_globals["SHOW_VALIDATION_COVERAGE_FALLBACK_SIMILARITY_PERCENT"] = int(
        show_val.get("coverage_fallback_similarity_percent", 95)
    )
    module_globals["SHOW_VALIDATION_EXPLICIT_PODCAST_PAGE_SCORE"] = int(
        show_val.get("explicit_podcast_page_score", 10)
    )
    module_globals["SHOW_VALIDATION_PODCAST_LIKE_PASS_MINIMUM"] = int(
        show_val.get("podcast_like_pass_minimum_score", 3)
    )
    module_globals["SHOW_VALIDATION_LARGE_CAST_MINIMUM_LINKS"] = int(
        show_val.get("large_cast_minimum_credit_links", 5)
    )
    module_globals["SHOW_VALIDATION_LARGE_CAST_PENALTY"] = int(show_val.get("large_cast_score_penalty", 2))
    module_globals["SHOW_VALIDATION_GENRE_KEYWORD_BOOST"] = int(show_val.get("genre_keyword_boost", 1))
    module_globals["SHOW_VALIDATION_RISK_HIGH_BELOW_SCORE"] = int(
        show_val.get("false_positive_risk_high_below_score", 3)
    )
    module_globals["SHOW_VALIDATION_RISK_MEDIUM_BELOW_SCORE"] = int(
        show_val.get("false_positive_risk_medium_below_score", 10)
    )
    module_globals["SHOW_VALIDATION_REJECT_BELOW_PODCAST_SCORE"] = int(
        show_val.get("reject_validation_below_podcast_score", 0)
    )
    module_globals["SHOW_VALIDATION_SCORE_DESCRIPTION_PODCAST"] = int(
        scoring.get("description_podcast_word", 3)
    )
    module_globals["SHOW_VALIDATION_SCORE_DESCRIPTION_EPISODE"] = int(
        scoring.get("description_episode_word", 2)
    )
    module_globals["SHOW_VALIDATION_SCORE_DESCRIPTION_HOSTED"] = int(
        scoring.get("description_hosted_presented", 2)
    )
    module_globals["SHOW_VALIDATION_SCORE_DESCRIPTION_WEEKLY_DAILY"] = int(
        scoring.get("description_weekly_daily", 1)
    )
    module_globals["SHOW_VALIDATION_SCORE_DESCRIPTION_GUESTS"] = int(scoring.get("description_guests", 1))


def _apply_logging_settings(log: Dict[str, Any]) -> None:
    module_globals = globals()
    module_globals["LOG_LEVEL"] = str(log.get("level", "INFO"))


def apply_yaml(raw: Dict[str, Any]) -> None:
    """Populate module globals from parsed YAML."""
    paths = raw.get("paths", {})
    sqlite = raw.get("sqlite", {})
    checkpointing_raw = raw.get("checkpointing", {})
    http_client = raw.get("http_client") or raw.get("scraping", {})
    circuit_breaker_raw = raw.get("circuit_breaker", {})
    matching_config = raw.get("matching", {})
    show_val = raw.get("show_validation", {})
    scoring = show_val.get("scoring", {})
    log = raw.get("logging", {})

    _apply_path_settings(paths)
    _apply_sqlite_and_checkpoint(sqlite, checkpointing_raw)
    _apply_http_client_settings(http_client)
    _apply_circuit_breaker_settings(circuit_breaker_raw)
    _apply_matching_settings(matching_config)
    _apply_show_validation_settings(show_val, scoring)
    _apply_logging_settings(log)


def load_config(path: Optional[Path] = None) -> None:
    """Load ``config.yaml`` from repo root (or ``path``)."""
    global _CONFIG_LOADED, _CONFIG_SOURCE_PATH

    if _CONFIG_LOADED:
        previous_path = str(_CONFIG_SOURCE_PATH) if _CONFIG_SOURCE_PATH is not None else "<unknown>"
        requested_path = str(path) if path is not None else str(ROOT_DIR / "config.yaml")
        raise RuntimeError(
            "Configuration was already loaded and cannot be reloaded in-process. "
            f"loaded_from={previous_path} requested={requested_path}"
        )

    cfg_path = path or (ROOT_DIR / "config.yaml")
    with cfg_path.open(encoding="utf-8") as handle:
        apply_yaml(yaml.safe_load(handle))
    _CONFIG_LOADED = True
    _CONFIG_SOURCE_PATH = cfg_path
