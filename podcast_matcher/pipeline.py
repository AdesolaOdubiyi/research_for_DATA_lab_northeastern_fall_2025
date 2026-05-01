"""Batch orchestration: ingest shows, resolve catalog hits, match episodes, export."""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import List, Optional

import podcast_matcher.config as config
from podcast_matcher.database import DatabaseManager
from podcast_matcher.imdb_client import IMDbClient
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
    imdb_client: IMDbClient,
    limit: Optional[int] = None,
) -> None:
    """Process grouped shows: search, validate, fetch episodes, match, persist."""
    ensure_output_dir()
    db.recover_from_crash()

    if limit is not None:
        shows = shows[:limit]

    total_episodes = sum(len(show["episodes"]) for show in shows)
    logger.info("Loaded %s shows with %s total episodes", len(shows), total_episodes)

    stats = {
        "shows_searched": 0,
        "shows_found": 0,
        "shows_not_found": 0,
        "episodes_total": 0,
        "episodes_matched": 0,
        "episodes_with_ratings": 0,
        "match_types": Counter(),
        "false_positive_risks": Counter(),
    }

    for idx, show in enumerate(shows, 1):
        show_rss = str(show["show_rss"])
        show_name = str(show["show_name"])
        spotify_uri = show.get("spotify_show_uri")
        spotify_uri_str = str(spotify_uri) if spotify_uri else None
        db.upsert_show(show_rss, show_name, "processing", spotify_uri_str)
        stats["shows_searched"] += 1
        stats["episodes_total"] += len(show["episodes"])
        logger.info("(%s/%s) Processing show '%s'", idx, len(shows), show_name)
        db.log_processing_event(show_rss, show_name, "start", "info", f"Processing show {idx}/{len(shows)}")
        try:
            candidate_tconst = imdb_client.search_show(show_name)
            if not candidate_tconst:
                stats["shows_not_found"] += 1
                db.update_show(show_rss, "not_found")
                logger.warning("No catalog hit for '%s'", show_name)
                db.log_processing_event(show_rss, show_name, "search", "warning", "No catalog result")
                continue
            valid, imdb_title, similarity, risk, validated_tconst = validate_show_match(
                imdb_client, candidate_tconst, show_name
            )
            if not valid or not validated_tconst:
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
                continue
            imdb_eps = imdb_client.fetch_episodes(validated_tconst)
            if not imdb_eps:
                stats["shows_not_found"] += 1
                db.update_show(show_rss, "no_catalog_episodes")
                logger.warning("Show '%s' has no catalog episodes", show_name)
                db.log_processing_event(show_rss, show_name, "episodes", "warning", "No catalog episodes")
                continue
            logger.info(
                "Fetched %s catalog episodes for '%s', matching %s source episodes",
                len(imdb_eps),
                show_name,
                len(show["episodes"]),
            )
            matches = match_episodes(show["episodes"], imdb_eps)
            for i, row in enumerate(show["episodes"]):
                if i < len(matches):
                    matches[i]["spotify_episode_uri"] = row.get("spotify_episode_uri")
            if len(matches) != len(show["episodes"]):
                logger.error(
                    "Episode count mismatch matches=%s episodes=%s",
                    len(matches),
                    len(show["episodes"]),
                )
                db.log_processing_event(
                    show_rss,
                    show_name,
                    "matching",
                    "error",
                    f"Episode count mismatch: {len(matches)} vs {len(show['episodes'])}",
                )
            db.insert_episode_matches(show_rss, matches)
            db.update_show(show_rss, "found", imdb_tconst=validated_tconst, false_positive_risk=risk)
            stats["shows_found"] += 1
            risk_key = str(risk or "none")
            stats["false_positive_risks"][risk_key] += 1
            matched_count = sum(1 for m in matches if m["match_type"] != "unmatched")
            rating_count = sum(1 for m in matches if m.get("imdb_rating") is not None)
            stats["episodes_matched"] += matched_count
            stats["episodes_with_ratings"] += rating_count
            for match in matches:
                stats["match_types"][str(match["match_type"])] += 1
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
                risk or "n/a",
            )
        except Exception as exc:  # noqa: BLE001 — per-show boundary
            stats["shows_not_found"] += 1
            db.update_show(show_rss, "error")
            db.log_processing_event(show_rss, show_name, "error", "error", "Unhandled exception", str(exc))
            logger.exception("Show failed show_rss=%s", show_rss)
            continue

        if idx % config.CHECKPOINT_FREQUENCY == 0:
            match_rate = stats["episodes_matched"] / stats["episodes_total"] if stats["episodes_total"] else 0
            logger.info(
                "Checkpoint @ show %s: %s shows processed, %.2f%% episode match rate",
                idx,
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

    summary = {
        "shows_searched": stats["shows_searched"],
        "shows_found": stats["shows_found"],
        "shows_not_found": stats["shows_not_found"],
        "episodes_total": stats["episodes_total"],
        "episodes_matched": stats["episodes_matched"],
        "episodes_with_ratings": stats["episodes_with_ratings"],
        "match_rate": (stats["episodes_matched"] / stats["episodes_total"]) if stats["episodes_total"] else 0,
        "rating_coverage": (stats["episodes_with_ratings"] / stats["episodes_total"])
        if stats["episodes_total"]
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


def load_input_shows(path: Path, fmt: str, db: DatabaseManager) -> List[dict]:
    """Load grouped shows from JSONL or TSV."""
    fmt_norm = fmt.lower().strip()
    if fmt_norm == "jsonl":
        return load_shows_from_jsonl(path, db)
    if fmt_norm == "tsv":
        return load_shows_from_tsv(path, db)
    raise ValueError(f"Unsupported format: {fmt}")
