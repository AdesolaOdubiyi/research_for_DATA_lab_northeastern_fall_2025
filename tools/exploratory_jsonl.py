"""Basic JSONL field coverage stats (optionally gzip-compressed)."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


def iter_lines(path: Path) -> Iterable[str]:
    """Yield text lines from plain or gzip JSONL."""
    if path.suffix.lower() == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
            yield from handle
    else:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            yield from handle


def summarize(path: Path, max_lines: Optional[int]) -> None:
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
    for i, line in enumerate(iter_lines(path), 1):
        if max_lines is not None and i > max_lines:
            break
        line = line.strip()
        if not line:
            continue
        lines_seen += 1
        try:
            row: Dict[str, Any] = json.loads(line)
        except json.JSONDecodeError:
            bad_json += 1
            continue
        for k in keys:
            v = row.get(k)
            if v is not None and v != "":
                present[k] += 1
    cap_note = f" (cap {max_lines})" if max_lines is not None else ""
    print(f"Non-empty JSON lines scanned{cap_note}: {lines_seen}")
    print(f"JSON decode errors: {bad_json}")
    for k in keys:
        print(f"  {k}: {present[k]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="JSONL or JSONL.gz path")
    parser.add_argument("--max-lines", type=int, default=None, help="Cap lines for quick sampling")
    args = parser.parse_args()
    if not args.path.is_file():
        print(f"Not a file: {args.path}", file=sys.stderr)
        raise SystemExit(1)
    summarize(args.path, args.max_lines)


if __name__ == "__main__":
    main()
