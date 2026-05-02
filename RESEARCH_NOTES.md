# Research Notes — DATA Lab (Northeastern, Fall 2025)

This document covers what was tried, what failed, why certain pivots happened, and what the data ultimately showed. It is a technical companion to the main README, written for anyone who wants to understand the reasoning behind the architecture and the research outcomes.
---

## The Research Question

The DATA Lab needed episode-level podcast ratings at scale: quality scores or user ratings attached to individual episodes, not just shows, across a dataset of 105,000 episodes from 18,376 shows sourced from Spotify. The goal was to use those ratings to evaluate sentiment analysis on podcasts on the web as an up and coming form of entertainment. The pipeline in this repository was built to retrieve, match, and store that data reliably.

What the semester proved is that this data does not exist at scale on any platform evaluated. This finding saved the lab from spending further resources pursuing this data.

Platform 1 is anonymized for compliance with vendor terms.
---

## Platform 1 — The First Catalog (Reverse-Engineered API)

The first platform evaluated had no public API. Initial attempts used standard HTML scraping, which worked at small scale but hit pagination limits almost immediately when applied to a dataset of this size.

The solution was to reverse-engineer the platform's internal GraphQL API, identifying the persisted query hash from network traffic, reconstructing the pagination flow, and building a client that could walk through episode lists programmatically. This worked and the pipeline was able to retrieve episode data at scale.

The match results, however, did not. After processing 16,363 episodes, the platform returned ratings for a statistically negligible fraction of them. The coverage was so low (0.006%) that continuing was not defensible from a research economics standpoint. At that point, I made a recommendation to the lab that this platform is not a viable source for episode-level ratings, and further engineering effort here has a negative expected value. The lab accepted the recommendation and we pivoted.

The infrastructure built for this platform became the foundation for everything that followed.

---

## Platform 2 — Podchaser (Official API)

Podchaser had an official API and documented episode-level ratings. Therefore, instead of name-based fuzzy matching, the pipeline used RSS feeds and Spotify IDs as primary identifiers, falling back to name-based search only when exact identifiers were unavailable. This was the right call — RSS-feed matching produced zero false positives, while pure fuzzy name matching had been causing false positive matches on the first platform that required manual correction.

Coverage results on an initial set of 15 shows: 100% show-level match rate, ~60% episode-level rating coverage. That is a meaningful number. It is also the ceiling — not every episode has been rated by users, and that gap is not an engineering problem.

**On API costs.** Podchaser operates on a point-based pricing model. During development and testing, I consumed the full 25,000 monthly point allocation. This is worth naming directly: real-world API development at any reasonable scale is expensive, and testing a pipeline that processes tens of thousands of records will burn through free tiers. This is not unique to this project — it is a standard reality of data engineering that is easy to underestimate before you have run into it. The lesson here is to stub external calls aggressively during development and reserve real API quota for validated runs against production data.

The Podchaser integration demonstrated what was achievable: show-level ratings at 60% coverage, retrievable reliably via the official API, with a clear cost model. I surfaced this to the lab as a viable path forward for show-level analysis, while being explicit that episode-level ratings remained sparse and expensive to retrieve at the full dataset scale.

---

## The Distinction That Mattered Most

One of the more useful contributions during this project was clarifying a distinction the research team had not fully drawn: the difference between **rating data** and **popularity metrics**.

Rating data is qualitative — user scores, review counts, explicit quality signals. Episode-level rating data of this kind is sparse to nonexistent across the platforms evaluated.

Popularity metrics are quantitative but different — download estimates, listener counts, play counts. These exist in more places and at better coverage, but they measure something different. Framing expectations correctly around this distinction changed how the team evaluated Rephonic, the final platform on the evaluation list, and avoided a situation where the team would have interpreted high popularity coverage as a proxy for the rating data they actually needed.

---

## Platform 3 — YouTube

YouTube was evaluated briefly as a potential source of engagement signals. YouTube eliminated public dislike counts in 2021, which removed the primary signal of interest. This platform was ruled out quickly.

---

## Platform 4 — Rephonic

Rephonic was identified as the final viable alternative before the end of the semester — a platform with download estimates and some show-level data that could potentially serve as popularity proxies. The evaluation framework, cost estimates, and expected coverage projections were documented and passed to the lab. At that point my involvement in the project concluded for the semester. The lab's evaluation of Rephonic continued independently.

---

## Architecture Decisions Worth Noting

**Why two databases.** Separating `results.db` (pipeline outputs) from `audit.db` (processing log, errors, checkpoints) was a deliberate choice. Mixing operational data with audit data in a single schema makes it harder to query either cleanly and creates risk of audit records being affected by schema migrations to the results tables. Keeping them separate also means a corrupted results database does not take the audit trail with it.

**Why WAL mode.** Multi-day scraping runs with periodic checkpoints create a realistic risk of mid-run crashes. Write-Ahead Logging means that in-progress writes are not lost on crash — the database can recover to the last consistent checkpoint. For a run that takes 20–30 hours, this is not optional.

**Why the circuit breaker.** Aggressive scraping against an external API without a backoff mechanism is how you get IP-banned. The circuit breaker tracks consecutive failure counts and pauses the run — with an email alert — rather than hammering a platform that is clearly throttling or rejecting requests. The thresholds (25 consecutive 503s, 10 network errors, 15-error early warning) were calibrated based on observed behavior during development runs, not set arbitrarily.

**Why checkpointing every N shows.** The `checkpoint_frequency` in `config.yaml` controls how often the pipeline writes its progress state to disk. Too frequent and you add overhead; too infrequent and a crash means replaying more work. The default of 50 shows reflects the practical tradeoff at the dataset sizes involved.

---

## What This Project Is Not

This is not a general-purpose podcast data pipeline. It is a research tool built for a specific dataset, a specific research question, and a specific set of platforms. The offline mode, the sample data, and the configurable env-gating are there to make the architecture reproducible and demonstrable without redistributing proprietary data or operational credentials.

The value of this repository is not the data it produced — that stays with the lab. The value is the architecture: a reliable, observable, crash-safe pipeline for large-scale external API matching, built under real research constraints, with documented decisions and honest accounting of what worked and what did not.