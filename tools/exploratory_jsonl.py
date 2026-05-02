"""Basic JSONL field coverage stats (optionally gzip-compressed)."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


def iterate_lines(path: Path) -> Iterable[str]:
    """Yield text lines from plain or gzip JSONL."""
    if path.suffix.lower() == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
            yield from handle
    else:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            yield from handle


def summarize_jsonl_field_coverage(path: Path, max_lines: Optional[int]) -> None:
    """Print presence counts for a small set of common podcast-export keys."""
    keys = [
        "podTitle",
        "rssUrl",
        "epTitle",
        "mp3url",
        "durationSeconds",
        "episodeDateLocalized",
        "episode_uri",
        "show_uri",
    ]
    present = Counter()
    bad_json = 0
    lines_seen = 0
    for line_index, raw_line in enumerate(iterate_lines(path), 1):
        if max_lines is not None and line_index > max_lines:
            break
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        lines_seen += 1
        try:
            parsed_row: Dict[str, Any] = json.loads(raw_line)
        except json.JSONDecodeError:
            bad_json += 1
            continue
        for field_name in keys:
            field_value = parsed_row.get(field_name)
            if field_value is not None and field_value != "":
                present[field_name] += 1
    cap_note = f" (cap {max_lines})" if max_lines is not None else ""
    print(f"Non-empty JSON lines scanned{cap_note}: {lines_seen}")
    print(f"JSON decode errors: {bad_json}")
    for field_name in keys:
        print(f"  {field_name}: {present[field_name]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="JSONL or JSONL.gz path")
    parser.add_argument("--max-lines", type=int, default=None, help="Cap lines for quick sampling")
    args = parser.parse_args()
    if not args.path.is_file():
        print(f"Not a file: {args.path}", file=sys.stderr)
        raise SystemExit(1)
    summarize_jsonl_field_coverage(args.path, args.max_lines)


if __name__ == "__main__":
    main()
