"""CLI entry: offline sample run by default."""

from __future__ import annotations

import argparse
from pathlib import Path

import podcast_matcher.config as config
from podcast_matcher.database import DatabaseManager
from podcast_matcher.imdb_client import IMDbClient
from podcast_matcher.pipeline import configure_logging, load_input_shows, process_shows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Match podcast episode metadata to a catalog (offline fixtures by default)."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Path to JSONL or TSV input (defaults to path from config.yaml after load)",
    )
    parser.add_argument(
        "--format",
        choices=("jsonl", "tsv"),
        default="jsonl",
        help="Input file format",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Override path to config.yaml",
    )
    parser.add_argument("--limit", type=int, default=None, help="Max number of shows to process")
    args = parser.parse_args()

    config.load_config(args.config)
    input_path = args.input or config.JSONL_PATH
    configure_logging()
    db = DatabaseManager()
    db.init()
    shows = load_input_shows(input_path, args.format, db)
    client = IMDbClient()
    process_shows(shows, db, client, limit=args.limit)
    db.close()


if __name__ == "__main__":
    main()
