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
    episodes = 0
    with tsv_path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            su = (row.get("show_uri") or "").strip()
            if su:
                shows.add(su)
            episodes += 1
    return len(shows), episodes


def db_counts(db_path: Path) -> Dict[str, int]:
    """Summarize ``shows`` and ``episodes`` tables written by the batch pipeline."""
    conn = sqlite3.connect(db_path)
    try:
        show_total = conn.execute("SELECT COUNT(*) FROM shows;").fetchone()[0]
        ep_total = conn.execute("SELECT COUNT(*) FROM episodes;").fetchone()[0]
        matched = conn.execute(
            "SELECT COUNT(*) FROM episodes WHERE match_type IS NOT NULL AND match_type != 'unmatched';"
        ).fetchone()[0]
        with_rating = conn.execute(
            "SELECT COUNT(*) FROM episodes WHERE imdb_rating IS NOT NULL;"
        ).fetchone()[0]
        by_status = dict(conn.execute("SELECT status, COUNT(*) FROM shows GROUP BY status;").fetchall())
    finally:
        conn.close()
    return {
        "shows": int(show_total),
        "episodes": int(ep_total),
        "matched_episodes": int(matched),
        "episodes_with_rating": int(with_rating),
        "shows_by_status": by_status,
    }


def episodes_per_show_tsv(tsv_path: Path) -> DefaultDict[str, int]:
    out: DefaultDict[str, int] = defaultdict(int)
    with tsv_path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            su = (row.get("show_uri") or "").strip()
            if su:
                out[su] += 1
    return out


def episodes_per_show_db(db_path: Path) -> DefaultDict[str, int]:
    out: DefaultDict[str, int] = defaultdict(int)
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
        for key, n in rows:
            out[str(key)] += int(n)
    finally:
        conn.close()
    return out


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

    u, ep = tsv_counts(args.tsv)
    d = db_counts(args.db)
    print("TSV unique show_uri:", u)
    print("TSV episode rows:", ep)
    print("DB shows:", d["shows"], d["shows_by_status"])
    print("DB episode rows:", d["episodes"])
    print("DB matched episodes (match_type != unmatched):", d["matched_episodes"])
    print("DB episodes with numeric rating:", d["episodes_with_rating"])

    tsv_dist = episodes_per_show_tsv(args.tsv)
    db_dist = episodes_per_show_db(args.db)
    overlap = set(tsv_dist).intersection(db_dist)
    if overlap:
        diffs = [(k, tsv_dist[k], db_dist[k]) for k in sorted(overlap) if tsv_dist[k] != db_dist[k]]
        print("Sample per-show episode count mismatches (up to 10):", diffs[:10])


if __name__ == "__main__":
    main()
