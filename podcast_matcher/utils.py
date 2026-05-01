"""Shared helpers: paths, JSONL/TSV ingestion, title and date utilities."""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import podcast_matcher.config as config


def ensure_output_dir() -> None:
    """Create the configured output directory."""
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def normalize_title(title: Optional[str]) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    if not title:
        return ""
    title = title.lower()
    title = re.sub(r"[^\w\s]", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def is_generic_title(title: Optional[str]) -> bool:
    """Detect very short or generic episode titles needing stricter checks."""
    normalized = normalize_title(title)
    words = normalized.split()
    if len(words) <= 2:
        return True
    generic_words = {"episode", "ep", "part", "intro", "update", "bonus", "trailer", "qa"}
    return all(word in generic_words for word in words)


def dates_match(
    sporc_timestamp_ms: Optional[int],
    imdb_date_dict: Optional[Dict[str, int]],
    tolerance_days: int,
) -> bool:
    """Compare podcast episode date (ms) to structured calendar fields within tolerance."""
    if not sporc_timestamp_ms or not imdb_date_dict:
        return False
    try:
        sporc_date = datetime.fromtimestamp(sporc_timestamp_ms / 1000).date()
        imdb_date = datetime(
            int(imdb_date_dict["year"]),
            int(imdb_date_dict.get("month", 1)),
            int(imdb_date_dict.get("day", 1)),
        ).date()
    except (ValueError, KeyError, TypeError):
        return False
    delta = abs((sporc_date - imdb_date).days)
    return delta <= tolerance_days


FIELD_MAPPING = {
    "show_name": "podTitle",
    "show_rss": "rssUrl",
    "episode_name": "epTitle",
    "episode_url": "mp3url",
    "duration_seconds": "durationSeconds",
    "category": "category1",
    "date": "episodeDateLocalized",
    "itunes_author": "itunesAuthor",
}


def extract_episode_fields(raw: Dict[str, object]) -> Tuple[Optional[Dict[str, object]], List[str]]:
    """Map a JSONL row to internal field names; return missing critical fields."""
    clean: Dict[str, object] = {}
    missing: List[str] = []
    for our_field, their_field in FIELD_MAPPING.items():
        value = raw.get(their_field)
        clean[our_field] = value
        if our_field in {"show_name", "show_rss"} and (value is None or value == ""):
            missing.append(our_field)
    return clean, missing


def load_shows_from_jsonl(path: Path, audit_logger: object) -> List[Dict[str, object]]:
    """Group JSONL lines by ``show_rss``."""
    shows: Dict[str, Dict[str, object]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_num, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                audit_logger.log_malformed_row(line_num, None, None, "json_decode_error", str(exc))
                continue
            clean, missing = extract_episode_fields(raw)
            if missing:
                audit_logger.log_malformed_row(
                    line_num,
                    str(clean.get("show_rss") or ""),
                    str(clean.get("show_name") or ""),
                    "missing_fields",
                    ", ".join(missing),
                )
                continue
            rss = str(clean["show_rss"])
            if rss not in shows:
                shows[rss] = {
                    "show_name": clean["show_name"],
                    "show_rss": rss,
                    "spotify_show_uri": raw.get("show_uri") or raw.get("spotify_show_uri"),
                    "itunes_author": clean.get("itunes_author"),
                    "category": clean.get("category"),
                    "episodes": [],
                }
            episode_row = {
                "episode_name": clean["episode_name"],
                "episode_url": clean.get("episode_url"),
                "date": clean.get("date"),
                "duration_seconds": clean.get("duration_seconds"),
                "spotify_episode_uri": raw.get("episode_uri") or raw.get("spotify_episode_uri"),
            }
            shows[rss]["episodes"].append(episode_row)
    return list(shows.values())


def load_shows_from_tsv(path: Path, audit_logger: object) -> List[Dict[str, object]]:
    """
    Group TSV rows by ``show_uri`` when present, attaching ``rss_url`` / ``rssUrl`` if column exists.

    Expected columns include at minimum: ``show_uri``, ``show_name``, ``episode_uri``,
    ``episode_name``, ``duration``. RSS column may be ``rss_url`` or ``rssUrl``.
    """
    shows: Dict[str, Dict[str, object]] = {}
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for line_num, row in enumerate(reader, start=2):
            show_uri = (row.get("show_uri") or "").strip()
            show_name = (row.get("show_name") or "").strip()
            rss = (row.get("rss_url") or row.get("rssUrl") or "").strip() or f"_synthetic_rss:{show_uri}"
            if not show_uri or not show_name:
                audit_logger.log_malformed_row(line_num, rss, show_name, "missing_fields", "show_uri or show_name")
                continue
            if rss not in shows:
                shows[rss] = {
                    "show_name": show_name,
                    "show_rss": rss,
                    "spotify_show_uri": show_uri,
                    "episodes": [],
                }
            duration_raw = row.get("duration") or ""
            try:
                duration_val = float(duration_raw) if duration_raw not in ("", None) else None
            except ValueError:
                duration_val = None
            shows[rss]["episodes"].append(
                {
                    "episode_name": (row.get("episode_name") or "").strip(),
                    "episode_url": row.get("mp3url") or row.get("episode_url"),
                    "date": row.get("episodeDateLocalized") or row.get("date_ms"),
                    "duration_seconds": duration_val,
                    "spotify_episode_uri": (row.get("episode_uri") or "").strip() or None,
                }
            )
    return list(shows.values())
