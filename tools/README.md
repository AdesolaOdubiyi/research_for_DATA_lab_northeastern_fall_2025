# Tools

One-page index for helper and investigation scripts. Each file’s module docstring and top comments carry the detailed behavior; this file only orients a reader in a few sentences.

## `file_lines_counter.py`

Counts lines in a text or ``.gz`` JSONL file without loading it into memory. Used during capacity planning to estimate batch runtime and storage. Run: ``python tools/file_lines_counter.py path/to/file.jsonl``.

## `exploratory_jsonl.py`

Lightweight field-presence and basic quality stats over a JSONL export (``.gz`` supported). Used early in the project to confirm which columns were reliable for ingestion and matching. Run: ``python tools/exploratory_jsonl.py path/to/file.jsonl --max-lines 50000``.

## `validate_tsv_against_results_db.py`

Compares a local metadata TSV (grouped by ``show_uri``) against ``outputs/results.db`` for row-count sanity and coarse reconciliation after a batch run. Helps catch partial reruns or import gaps before trusting exports.

## Scripts not shipped here (tier-2 public export)

During development, additional **network-backed** probes and HTML parsing experiments lived alongside this work. They are omitted from this repository so the public tree stays focused on **architecture and offline reproducibility**, without embedding third-party **operational URLs** or request recipes. Their purpose is summarized below so the research arc stays understandable.

- **`test_matcher_small_scale.py` (legacy)** — Early monolithic harness for show search, validation, and episode matching on a small subset; informed the modular package layout.
- **Legacy HTML / GraphQL probe scripts (not shipped)** — Parser and JSON-shape checks against remote responses during integration work; superseded by **offline mode** runs in this export.
- **`debug_house_of_rugby.py` (legacy)** — Single-show deep dive for a title-type edge case (episodic catalog quirks vs podcast feeds); informed matcher limitations in documentation.
- **`graphqltest.py` / `compare_search_strategies.py` / `debug_search.py` (legacy)** — Spikes for pagination, search variants, and ranking comparisons under real traffic; informed rate limiting and circuit-breaker behavior conceptually, not as copy-paste tooling.

If you maintain a **private research archive**, keep those originals there for full forensic context.
