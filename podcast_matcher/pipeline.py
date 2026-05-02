"""Batch orchestration: ingest shows, resolve catalog hits, match episodes, export."""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import podcast_matcher.config as config
from podcast_matcher.catalog_client import TitleCatalogClient
from podcast_matcher.database import DatabaseManager
from podcast_matcher.matcher_logic import match_episodes, validate_show_match
from podcast_matcher.utils import ensure_output_dir, load_shows_from_jsonl, load_shows_from_tsv

logger = logging.getLogger("podcast_matcher.pipeline")


def configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL),
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )


def process_shows(
    shows: List[dict],
    db: DatabaseManager,
    catalog_client: TitleCatalogClient,
    limit: Optional[int] = None,
) -> None:
    """Process grouped shows: search, validate, fetch episodes, match, persist."""
    ensure_output_dir()
    db.recover_from_crash()

    if limit is not None:
        shows = shows[:limit]

    total_episodes = sum(len(show["episodes"]) for show in shows)
    logger.info("Loaded %s shows with %s total episodes", len(shows), total_episodes)

    stats = _initialize_run_stats()
    total_shows = len(shows)

    for show_index, show in enumerate(shows, 1):
        _process_one_show(show_index, total_shows, show, db, catalog_client, stats)
        _create_checkpoint_if_due(show_index, db, stats)

    _write_summary_and_exports(db, stats)


def load_input_shows(path: Path, format: str, db: DatabaseManager) -> List[dict]:
    """Load grouped shows from JSONL or TSV."""
    normalized_format = format.strip().lower()
    if normalized_format == "jsonl":
        return load_shows_from_jsonl(path, db)
    if normalized_format == "tsv":
        return load_shows_from_tsv(path, db)
    raise ValueError(f"Unsupported format: {format}")


def _initialize_run_stats() -> Dict[str, Any]:
    return {
        "shows_searched": 0,
        "shows_found": 0,
        "shows_not_found": 0,
        "episodes_total": 0,
        "episodes_matched": 0,
        "episodes_with_ratings": 0,
        "match_types": Counter(),
        "false_positive_risks": Counter(),
    }


def _attach_spotify_episode_uris(matches: List[dict], source_episodes: List[dict]) -> None:
    for ep_index, episode_row in enumerate(source_episodes):
        if ep_index < len(matches):
            matches[ep_index]["spotify_episode_uri"] = episode_row.get("spotify_episode_uri")


def _create_checkpoint_if_due(
    show_index: int,
    db: DatabaseManager,
    stats: Dict[str, Any],
) -> None:
    if show_index % config.CHECKPOINT_FREQUENCY != 0:
        return
    episodes_total = stats["episodes_total"]
    match_rate = stats["episodes_matched"] / episodes_total if episodes_total else 0
    logger.info(
        "Checkpoint @ show %s: %s shows processed, %.2f%% episode match rate",
        show_index,
        stats["shows_searched"],
        match_rate * 100,
    )
    db.create_checkpoint(
        {
            "shows_processed": stats["shows_searched"],
            "shows_found": stats["shows_found"],
            "episodes_matched": stats["episodes_matched"],
            "match_rate": match_rate,
        },
        dict(stats["false_positive_risks"]),
    )


def _validate_show_and_load_catalog_episodes(
    catalog_client: TitleCatalogClient,
    db: DatabaseManager,
    stats: Dict[str, Any],
    show_rss: str,
    show_name: str,
    candidate_show_id: str,
) -> Optional[Tuple[str, List[Dict[str, Any]], Optional[float], Optional[str]]]:
    """
    Validate catalog hit, then load episode list.

    On failure: updates ``stats`` / DB like the inline pipeline and returns ``None``.
    """
    valid, _catalog_title, similarity, risk, validated_show_id = validate_show_match(
        catalog_client, candidate_show_id, show_name
    )
    if not valid or not validated_show_id:
        stats["shows_not_found"] += 1
        db.update_show(show_rss, "validation_failed")
        logger.warning("Validation failed for '%s' (similarity=%s)", show_name, similarity)
        db.log_processing_event(
            show_rss,
            show_name,
            "validate",
            "warning",
            f"Validation failed (similarity={similarity})",
        )
        return None

    catalog_eps = catalog_client.fetch_episodes(validated_show_id)
    if not catalog_eps:
        stats["shows_not_found"] += 1
        db.update_show(show_rss, "no_catalog_episodes")
        logger.warning("Show '%s' has no catalog episodes", show_name)
        db.log_processing_event(show_rss, show_name, "episodes", "warning", "No catalog episodes")
        return None

    return validated_show_id, catalog_eps, similarity, risk


def _persist_episode_matches_for_show(
    show_rss: str,
    show_name: str,
    validated_show_id: str,
    false_positive_risk: Optional[str],
    source_episodes: List[dict],
    catalog_eps: List[Dict[str, Any]],
    db: DatabaseManager,
    stats: Dict[str, Any],
) -> None:
    """Fuzzy-match episodes, persist rows, and roll up per-show statistics."""
    matches = match_episodes(source_episodes, catalog_eps)
    _attach_spotify_episode_uris(matches, source_episodes)

    if len(matches) != len(source_episodes):
        stats["shows_not_found"] += 1
        db.update_show(show_rss, "matching_failed")
        logger.error(
            "Episode count mismatch matches=%s episodes=%s",
            len(matches),
            len(source_episodes),
        )
        db.log_processing_event(
            show_rss,
            show_name,
            "matching",
            "error",
            f"Episode count mismatch: {len(matches)} vs {len(source_episodes)}",
        )
        return

    db.insert_episode_matches(show_rss, matches)
    db.update_show(show_rss, "found", catalog_show_id=validated_show_id, false_positive_risk=false_positive_risk)
    stats["shows_found"] += 1
    risk_key = str(false_positive_risk or "none")
    stats["false_positive_risks"][risk_key] += 1
    matched_count = sum(1 for match_row in matches if match_row["match_type"] != "unmatched")
    rating_count = sum(1 for match_row in matches if match_row.get("catalog_rating") is not None)
    stats["episodes_matched"] += matched_count
    stats["episodes_with_ratings"] += rating_count
    for match_row in matches:
        stats["match_types"][str(match_row["match_type"])] += 1
    db.log_processing_event(
        show_rss,
        show_name,
        "complete",
        "success",
        f"Matched {matched_count}/{len(matches)} episodes",
    )
    logger.info(
        "Completed '%s': matched %s/%s episodes (risk=%s)",
        show_name,
        matched_count,
        len(matches),
        false_positive_risk or "n/a",
    )


def _write_summary_and_exports(db: DatabaseManager, stats: Dict[str, Any]) -> None:
    episodes_total = stats["episodes_total"]
    summary = {
        "shows_searched": stats["shows_searched"],
        "shows_found": stats["shows_found"],
        "shows_not_found": stats["shows_not_found"],
        "episodes_total": episodes_total,
        "episodes_matched": stats["episodes_matched"],
        "episodes_with_ratings": stats["episodes_with_ratings"],
        "match_rate": (stats["episodes_matched"] / episodes_total) if episodes_total else 0,
        "rating_coverage": (stats["episodes_with_ratings"] / episodes_total)
        if episodes_total
        else 0,
        "match_types": dict(stats["match_types"]),
        "false_positive_risks": dict(stats["false_positive_risks"]),
    }
    logger.info(
        "Run complete: %s shows processed (%s found), %s/%s episodes matched (%.2f%%)",
        summary["shows_searched"],
        summary["shows_found"],
        summary["episodes_matched"],
        summary["episodes_total"],
        summary["match_rate"] * 100 if summary["episodes_total"] else 0,
    )
    Path(config.STATS_SUMMARY_PATH).parent.mkdir(parents=True, exist_ok=True)
    config.STATS_SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    db.save_statistics(summary)
    db.export_csv(config.MATCHED_CSV_PATH)
    db.export_json(config.MATCHED_JSON_PATH)


def _process_one_show(
    show_index: int,
    total_shows: int,
    show: dict,
    db: DatabaseManager,
    catalog_client: TitleCatalogClient,
    stats: Dict[str, Any],
) -> None:
    show_rss = str(show["show_rss"])
    show_name = str(show["show_name"])
    spotify_uri = show.get("spotify_show_uri")
    spotify_uri_str = str(spotify_uri) if spotify_uri else None
    source_episodes = show["episodes"]

    db.upsert_show(show_rss, show_name, "processing", spotify_uri_str)
    stats["shows_searched"] += 1
    stats["episodes_total"] += len(source_episodes)
    logger.info("(%s/%s) Processing show '%s'", show_index, total_shows, show_name)
    db.log_processing_event(
        show_rss, show_name, "start", "info", f"Processing show {show_index}/{total_shows}"
    )

    try:
        candidate_show_id = catalog_client.search_show(show_name)
        if not candidate_show_id:
            stats["shows_not_found"] += 1
            db.update_show(show_rss, "not_found")
            logger.warning("No catalog hit for '%s'", show_name)
            db.log_processing_event(show_rss, show_name, "search", "warning", "No catalog result")
            return

        loaded = _validate_show_and_load_catalog_episodes(
            catalog_client, db, stats, show_rss, show_name, candidate_show_id
        )
        if loaded is None:
            return

        validated_show_id, catalog_eps, _, risk = loaded
        logger.info(
            "Fetched %s catalog episodes for '%s', matching %s source episodes",
            len(catalog_eps),
            show_name,
            len(source_episodes),
        )
        _persist_episode_matches_for_show(
            show_rss,
            show_name,
            validated_show_id,
            risk,
            source_episodes,
            catalog_eps,
            db,
            stats,
        )
    except Exception as error:  # noqa: BLE001 — per-show boundary
        stats["shows_not_found"] += 1
        db.update_show(show_rss, "error")
        db.log_processing_event(
            show_rss, show_name, "error", "error", "Unhandled exception", str(error)
        )
        logger.exception("Show failed show_rss=%s", show_rss)
