# Research — DATA Lab (Northeastern, Fall 2025)

## About This Project

This repository is the technical foundation for a production-grade data engineering pipeline built during a Fall 2025 work-study with Northeastern's DATA Lab. The challenge was to match 105,000 podcast episodes across 18,376 shows from a Spotify dataset to external rating platforms so the researchers can attempt to analyze the sentiment of podcasts on the web. This needed to be done at scale, reliably, and without losing progress across multi-day runs.

The pipeline handles real failure modes such as circuit breaker that backs off after 25 consecutive failed API calls, Write-Ahead Logging across two SQLite databases for crash safety, and checkpointing so a 20–30 hour scraping run can resume from exactly where it stopped. The configuration values throughout reflect empirical decisions made across dozens of small-scale experiments before scaling up. For example, the request delay is set to 1.3 seconds due to testing I did against the external API after reverse engineering the graphQL payload. Similarly, the fuzzy match thresholds (90% show similarity, 85% parent series, 95%/85% episode high/medium, ±2 day date guard, 70% keyword coverage) were validated on multiple small-scale harness with manual spot-checks before larger runs.

The research question led to the interesting conclusion that episode-level podcast ratings simply do not exist at scale on any platform evaluated. That finding was backed by concrete coverage numbers, cost estimates, and documented failure modes for each platform. It saved the lab months of effort chasing data that does not exist in usable form.

For the full story of what was tried, what failed, why certain pivots were made, and what the data actually showed, see [RESEARCH_NOTES.md](RESEARCH_NOTES.md).

---

## Run

```bash
cd research_for_DATA_lab_northeastern_fall_2025
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m podcast_matcher.main
```

```bash
python -m podcast_matcher.main --input data/sample/shows.jsonl --format jsonl --limit 10
python -m podcast_matcher.main --input path\to\export.tsv --format tsv
python -m podcast_matcher.main --config path\to\config.yaml
```

## Inputs


| Kind                          | Default path                      | Override                                          |
| ----------------------------- | --------------------------------- | ------------------------------------------------- |
| Episode JSONL                 | `data/sample/shows.jsonl`         | `paths.input_jsonl` in `config.yaml` or `--input` |
| Catalog sample (offline mode) | `data/sample/offline_vendor.json` | `paths.offline_catalog_sample` in `config.yaml`   |


Legacy YAML key `paths.offline_vendor_fixture` is still read if `offline_catalog_sample` is absent.

## Outputs


| Artifact     | Default path                   |
| ------------ | ------------------------------ |
| Results DB   | `outputs/results.db`           |
| Audit DB     | `outputs/audit.db`             |
| Matched CSV  | `outputs/matched_results.csv`  |
| Matched JSON | `outputs/matched_results.json` |
| Run summary  | `outputs/stats_summary.json`   |


All paths are configurable under `paths` in `config.yaml`.

## Configuration


| Block             | Purpose                                  |
| ----------------- | ---------------------------------------- |
| `paths`           | Input/output locations                   |
| `sqlite`          | e.g. `use_wal`                           |
| `checkpointing`   | Checkpoint every N shows                 |
| `http_client`     | Throttle, timeout, retries for live HTTP |
| `circuit_breaker` | 503 / network backoff                    |
| `matching`        | Fuzzy thresholds, date tolerance         |
| `show_validation` | Show-level HTML heuristics               |
| `logging`         | Log level                                |


Legacy YAML key `scraping` is accepted as an alias for `http_client`.

## Environment Variables

Live catalog HTTP is off unless `CATALOG_HTTP_ENABLED` is truthy. Required and optional variables are listed in `.env.example`.


| Variable                               | Required when live | Role                                         |
| -------------------------------------- | ------------------ | -------------------------------------------- |
| `CATALOG_HTTP_ENABLED`                 | —                  | Enables live mode                            |
| `CATALOG_SEARCH_URL_PODCAST_TEMPLATE`  | yes                | Search URL with `{query}`                    |
| `CATALOG_TITLE_PAGE_URL_TEMPLATE`      | yes                | Title page URL with `{catalog_show_id}`      |
| `CATALOG_GRAPHQL_HTTP_URL`             | yes                | GraphQL endpoint                             |
| `CATALOG_HTTP_ORIGIN_HEADER`           | yes                | `Origin` header                              |
| `CATALOG_HTTP_REFERER_HEADER`          | yes                | `Referer` header                             |
| `CATALOG_GRAPHQL_PERSISTED_HASH`       | yes                | Persisted query hash                         |
| `CATALOG_GRAPHQL_VARIABLES_RETURN_URL` | yes                | GraphQL variable `returnUrl`                 |
| `CATALOG_SEARCH_URL_FALLBACK_TEMPLATE` | no                 | Alternate search URL with `{query}`          |
| `CATALOG_GRAPHQL_OPERATION_NAME`       | no                 | Defaults to `TitleEpisodesSubPagePagination` |


Optional SMTP variables for notifications: see `.env.example`.

## Schema Notes

`results.db` is stamped with `PRAGMA user_version = 1`. If startup raises a schema/version error, delete `outputs/results.db` and re-run.

Show row statuses: `processing`, `pending`, `found`, `not_found`, `validation_failed`, `no_catalog_episodes`, `matching_failed`, `error`.

## Tools

See `tools/README.md`.

## Further Reading

The architectural decisions, platform evaluations, pivot rationale, and research findings are documented in [RESEARCH_NOTES.md](RESEARCH_NOTES.md).

## License

Code is for portfolio and educational use. Third-party terms apply for any live catalog integration.