# Research — DATA Lab (Northeastern, Fall 2025)

Public export of a **batch data-engineering** project: ingest podcast metadata at scale, persist state in **SQLite with WAL**, checkpointing, structured audit logs, fuzzy episode alignment, and conservative **show-level validation** heuristics. The research run covered on the order of **100k+ episodes** across **18k+ shows**; this repository keeps the **architecture** and an **offline synthetic sample** so others can reproduce the pipeline without redistributing study datasets.

## Quick start (offline, no network)

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
python -m podcast_matcher.main
```

Outputs land under `outputs/` (`results.db`, `audit.db`, CSV/JSON exports, `stats_summary.json`). Input defaults to `data/sample/shows.jsonl`; catalog responses default to `data/sample/offline_vendor.json`.

CLI options:

```text
python -m podcast_matcher.main --input data/sample/shows.jsonl --format jsonl --limit 10
python -m podcast_matcher.main --input path/to/export.tsv --format tsv
```

## Reproducibility and third-party boundaries

This repository documents a **durable batch pipeline** (ingestion → validation → matching → SQLite + exports + audit). **Remote catalog access** (HTTP search + episode metadata APIs) is modeled as a **replaceable adapter**. The version published here ships an **offline fixture-backed adapter** so the default path is **fully local** and does not embed **vendor hostnames, endpoint URLs, or operational request payloads** in source code.

That keeps the emphasis on **data engineering practice** (schema design, WAL, checkpointing, observability, matching discipline) and avoids publishing copy-paste recipes for third-party services. It also matches how we treat **research inputs**: synthetic samples ship in-repo; **real study feeds are not posted** here out of ordinary care for dataset handling and agreements—not because the pipeline is secret.

## Layout

| Path | Role |
|------|------|
| `podcast_matcher/` | Package: CLI (`main.py`), pipeline, SQLite, matcher, offline catalog client |
| `config.yaml` | Tunables (thresholds, paths); no secrets |
| `.env.example` | Optional SMTP knobs for notifications |
| `data/sample/` | Synthetic JSONL + offline “vendor” JSON fixtures |
| `tools/` | Small local QA helpers; see `tools/README.md` |

## Configuration

- Edit **`config.yaml`** for match thresholds, checkpoint cadence, and output paths.
- Copy **`.env.example`** → `.env` if you want optional email alerts (`SMTP_*`, `NOTIFY_*`). Nothing in `.env` is committed.

## Design notes

- **Canonical show key**: `show_rss` (RSS URL). Optional `spotify_show_uri` / `spotify_episode_uri` columns capture platform identifiers when present in the input file.
- **Dual databases**: `results.db` (shows, episodes, run statistics) and `audit.db` (processing log, malformed rows, checkpoints), both with WAL enabled when configured.
- **Show validation**: HTML-based heuristics reduce false positives before episode matching (see `podcast_matcher/matcher_logic.py`).
- **Episode matching**: `rapidfuzz` token similarity plus optional date proximity (see `config.yaml`).

## Tools

See [`tools/README.md`](tools/README.md) for short descriptions of helper scripts and a note on **legacy network investigations** that are intentionally omitted from this public tree.

## License / disclaimer

Code is provided for **portfolio and educational** context. Third-party data and service terms still apply if you wire a live adapter in a private fork. This export does not include production datasets or credentials.
