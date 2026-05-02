"""Compare a local metadata TSV to ``outputs/results.db`` (coarse QA)."""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import DefaultDict, Dict, Tuple


def tsv_counts(tsv_path: Path) -> Tuple[int, int]:
    """Return (unique_show_uri_count, total_episode_rows)."""
    shows: set[str] = set()
    episode_row_total = 0
    with tsv_path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            show_uri_val = (row.get("show_uri") or "").strip()
            if show_uri_val:
                shows.add(show_uri_val)
            episode_row_total += 1
    return len(shows), episode_row_total


def db_counts(db_path: Path) -> Dict[str, int]:
    """Summarize ``shows`` and ``episodes`` tables written by the batch pipeline."""
    conn = sqlite3.connect(db_path)
    try:
        show_total = conn.execute("SELECT COUNT(*) FROM shows;").fetchone()[0]
        episode_total = conn.execute("SELECT COUNT(*) FROM episodes;").fetchone()[0]
        matched_total = conn.execute(
            "SELECT COUNT(*) FROM episodes WHERE match_type IS NOT NULL AND match_type != 'unmatched';"
        ).fetchone()[0]
        with_rating_total = conn.execute(
            "SELECT COUNT(*) FROM episodes WHERE catalog_rating IS NOT NULL;"
        ).fetchone()[0]
        by_status = dict(conn.execute("SELECT status, COUNT(*) FROM shows GROUP BY status;").fetchall())
    finally:
        conn.close()
    return {
        "shows": int(show_total),
        "episodes": int(episode_total),
        "matched_episodes": int(matched_total),
        "episodes_with_rating": int(with_rating_total),
        "shows_by_status": by_status,
    }


def episodes_per_show_tsv(tsv_path: Path) -> DefaultDict[str, int]:
    counts_by_show: DefaultDict[str, int] = defaultdict(int)
    with tsv_path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            show_uri_val = (row.get("show_uri") or "").strip()
            if show_uri_val:
                counts_by_show[show_uri_val] += 1
    return counts_by_show


def episodes_per_show_db(db_path: Path) -> DefaultDict[str, int]:
    counts_by_show: DefaultDict[str, int] = defaultdict(int)
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT COALESCE(spotify_show_uri, show_rss), COUNT(*)
            FROM shows s
            JOIN episodes e ON e.show_rss = s.show_rss
            GROUP BY 1;
            """
        ).fetchall()
        for group_key, episode_count in rows:
            counts_by_show[str(group_key)] += int(episode_count)
    finally:
        conn.close()
    return counts_by_show


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tsv", type=Path)
    parser.add_argument("db", type=Path, nargs="?", default=Path("outputs/results.db"))
    args = parser.parse_args()
    if not args.tsv.is_file():
        print(f"TSV not found: {args.tsv}", file=sys.stderr)
        raise SystemExit(1)
    if not args.db.is_file():
        print(f"DB not found: {args.db}", file=sys.stderr)
        raise SystemExit(1)

    uniq_shows, episode_rows = tsv_counts(args.tsv)
    db_summary = db_counts(args.db)
    print("TSV unique show_uri:", uniq_shows)
    print("TSV episode rows:", episode_rows)
    print("DB shows:", db_summary["shows"], db_summary["shows_by_status"])
    print("DB episode rows:", db_summary["episodes"])
    print("DB matched episodes (match_type != unmatched):", db_summary["matched_episodes"])
    print("DB episodes with numeric rating:", db_summary["episodes_with_rating"])

    tsv_dist = episodes_per_show_tsv(args.tsv)
    db_dist = episodes_per_show_db(args.db)
    overlap = set(tsv_dist).intersection(db_dist)
    if overlap:
        diffs = [
            (show_key, tsv_dist[show_key], db_dist[show_key])
            for show_key in sorted(overlap)
            if tsv_dist[show_key] != db_dist[show_key]
        ]
        print("Sample per-show episode count mismatches (up to 10):", diffs[:10])


if __name__ == "__main__":
    main()
