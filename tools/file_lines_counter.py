"""Count lines in a large text or gzip-compressed file (streaming, low memory)."""

from __future__ import annotations

import argparse
import gzip
import sys
from pathlib import Path


def count_lines(path: Path) -> int:
    """Return line count for plain text or ``*.gz`` UTF-8 text."""
    n = 0
    if path.suffix.lower() == ".gz":
        handle_ctx = gzip.open(path, "rt", encoding="utf-8", errors="replace")
    else:
        handle_ctx = path.open("r", encoding="utf-8", errors="replace")
    with handle_ctx as handle:
        for _ in handle:
            n += 1
    return n


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="File to count (.jsonl, .tsv, or .gz)")
    args = parser.parse_args()
    if not args.path.is_file():
        print(f"Not a file: {args.path}", file=sys.stderr)
        raise SystemExit(1)
    total = count_lines(args.path)
    print(f"Total lines: {total:,}")


if __name__ == "__main__":
    main()
