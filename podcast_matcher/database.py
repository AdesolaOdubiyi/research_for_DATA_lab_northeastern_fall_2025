"""Dual SQLite databases (results + audit) with WAL."""

from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import podcast_matcher.config as config


class DatabaseManager:
    """Operational ``results`` database plus ``audit`` trail."""

    def __init__(self) -> None:
        self.results_conn: Optional[sqlite3.Connection] = None
        self.audit_conn: Optional[sqlite3.Connection] = None

    def init(self) -> None:
        Path(config.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
        self.results_conn = sqlite3.connect(config.RESULTS_DB_PATH)
        self.audit_conn = sqlite3.connect(config.AUDIT_DB_PATH)
        if config.USE_WAL:
            self.results_conn.execute("PRAGMA journal_mode=WAL;")
            self.audit_conn.execute("PRAGMA journal_mode=WAL;")
        self._create_results_schema()
        self._create_audit_schema()

    def _create_results_schema(self) -> None:
        conn = self.results_conn
        assert conn is not None
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS shows (
                show_rss TEXT PRIMARY KEY,
                show_name TEXT NOT NULL,
                spotify_show_uri TEXT,
                imdb_tconst TEXT,
                false_positive_risk TEXT,
                status TEXT NOT NULL,
                last_updated TIMESTAMP
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                show_rss TEXT NOT NULL,
                spotify_episode_uri TEXT,
                episode_name TEXT NOT NULL,
                episode_url TEXT,
                episode_date_ms INTEGER,
                duration_seconds REAL,
                imdb_episode_tconst TEXT,
                imdb_rating REAL,
                match_type TEXT,
                confidence REAL,
                FOREIGN KEY (show_rss) REFERENCES shows(show_rss)
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS statistics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP NOT NULL,
                shows_searched INTEGER,
                shows_found INTEGER,
                shows_not_found INTEGER,
                episodes_total INTEGER,
                episodes_matched INTEGER,
                episodes_with_ratings INTEGER,
                match_types TEXT,
                false_positive_risks TEXT
            );
            """
        )
        conn.commit()

    def _create_audit_schema(self) -> None:
        conn = self.audit_conn
        assert conn is not None
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processing_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP NOT NULL,
                show_rss TEXT,
                show_name TEXT,
                stage TEXT,
                status TEXT,
                message TEXT,
                error_details TEXT
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP NOT NULL,
                shows_processed INTEGER,
                shows_found INTEGER,
                episodes_matched INTEGER,
                match_rate REAL,
                false_positive_risks TEXT
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS malformed_rows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP NOT NULL,
                line_number INTEGER,
                show_rss TEXT,
                show_name TEXT,
                issue_type TEXT,
                details TEXT
            );
            """
        )
        conn.commit()

    def recover_from_crash(self) -> None:
        assert self.results_conn is not None
        cur = self.results_conn.execute("SELECT show_rss FROM shows WHERE status='processing';")
        rows = cur.fetchall()
        for (show_rss,) in rows:
            self.results_conn.execute("DELETE FROM episodes WHERE show_rss=?;", (show_rss,))
            self.results_conn.execute("UPDATE shows SET status='pending' WHERE show_rss=?;", (show_rss,))
        self.results_conn.commit()

    def upsert_show(
        self,
        show_rss: str,
        show_name: str,
        status: str,
        spotify_show_uri: Optional[str] = None,
    ) -> None:
        assert self.results_conn is not None
        self.results_conn.execute(
            """
            INSERT INTO shows (show_rss, show_name, spotify_show_uri, status, last_updated)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(show_rss) DO UPDATE SET
                show_name=excluded.show_name,
                spotify_show_uri=COALESCE(excluded.spotify_show_uri, shows.spotify_show_uri),
                status=excluded.status,
                last_updated=excluded.last_updated;
            """,
            (show_rss, show_name, spotify_show_uri, status, datetime.utcnow()),
        )
        self.results_conn.commit()

    def update_show(
        self,
        show_rss: str,
        status: str,
        imdb_tconst: Optional[str] = None,
        false_positive_risk: Optional[str] = None,
    ) -> None:
        assert self.results_conn is not None
        self.results_conn.execute(
            """
            UPDATE shows
            SET status=?, imdb_tconst=?, false_positive_risk=?, last_updated=?
            WHERE show_rss=?;
            """,
            (status, imdb_tconst, false_positive_risk, datetime.utcnow(), show_rss),
        )
        self.results_conn.commit()

    def insert_episode_matches(self, show_rss: str, matches: List[Dict[str, object]]) -> None:
        rows = [
            (
                show_rss,
                match.get("spotify_episode_uri"),
                match["sporc_episode_name"],
                match.get("sporc_episode_url"),
                match.get("sporc_episode_date"),
                match.get("sporc_duration"),
                match.get("imdb_tconst"),
                match.get("imdb_rating"),
                match.get("match_type"),
                match.get("confidence"),
            )
            for match in matches
        ]
        assert self.results_conn is not None
        self.results_conn.executemany(
            """
            INSERT INTO episodes (
                show_rss, spotify_episode_uri, episode_name, episode_url, episode_date_ms,
                duration_seconds, imdb_episode_tconst, imdb_rating,
                match_type, confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            rows,
        )
        self.results_conn.commit()

    def log_processing_event(
        self,
        show_rss: Optional[str],
        show_name: Optional[str],
        stage: str,
        status: str,
        message: str,
        error_details: Optional[str] = None,
    ) -> None:
        assert self.audit_conn is not None
        self.audit_conn.execute(
            """
            INSERT INTO processing_log
            (timestamp, show_rss, show_name, stage, status, message, error_details)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (datetime.utcnow(), show_rss, show_name, stage, status, message, error_details),
        )
        self.audit_conn.commit()

    def log_malformed_row(
        self,
        line_number: int,
        show_rss: Optional[str],
        show_name: Optional[str],
        issue_type: str,
        details: str,
    ) -> None:
        assert self.audit_conn is not None
        self.audit_conn.execute(
            """
            INSERT INTO malformed_rows
            (timestamp, line_number, show_rss, show_name, issue_type, details)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (datetime.utcnow(), line_number, show_rss, show_name, issue_type, details),
        )
        self.audit_conn.commit()

    def create_checkpoint(self, stats: Dict[str, object], false_positive_risks: Dict[str, int]) -> None:
        assert self.audit_conn is not None
        self.audit_conn.execute(
            """
            INSERT INTO checkpoints
            (timestamp, shows_processed, shows_found, episodes_matched, match_rate, false_positive_risks)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (
                datetime.utcnow(),
                stats.get("shows_processed", 0),
                stats.get("shows_found", 0),
                stats.get("episodes_matched", 0),
                stats.get("match_rate", 0.0),
                json.dumps(false_positive_risks),
            ),
        )
        self.audit_conn.commit()

    def export_csv(self, path: Path) -> None:
        assert self.results_conn is not None
        cursor = self.results_conn.execute(
            """
            SELECT s.show_name, s.show_rss, s.spotify_show_uri, s.imdb_tconst, e.episode_name,
                   e.spotify_episode_uri, e.episode_url, e.episode_date_ms, e.duration_seconds,
                   e.imdb_episode_tconst, e.imdb_rating, e.match_type, e.confidence
            FROM episodes e
            JOIN shows s ON s.show_rss = e.show_rss;
            """
        )
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "show_name",
                    "show_rss",
                    "spotify_show_uri",
                    "imdb_show_tconst",
                    "episode_name",
                    "spotify_episode_uri",
                    "episode_url",
                    "episode_date_ms",
                    "duration_seconds",
                    "imdb_episode_tconst",
                    "imdb_rating",
                    "match_type",
                    "confidence",
                ]
            )
            writer.writerows(cursor.fetchall())

    def export_json(self, path: Path) -> None:
        assert self.results_conn is not None
        cursor = self.results_conn.execute(
            """
            SELECT s.show_name, s.show_rss, s.spotify_show_uri, s.imdb_tconst, s.false_positive_risk,
                   e.episode_name, e.spotify_episode_uri, e.episode_url, e.episode_date_ms,
                   e.duration_seconds, e.imdb_episode_tconst, e.imdb_rating, e.match_type, e.confidence
            FROM episodes e
            JOIN shows s ON s.show_rss = e.show_rss;
            """
        )
        columns = [d[0] for d in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        path.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    def save_statistics(self, summary: Dict[str, object]) -> None:
        assert self.results_conn is not None
        self.results_conn.execute(
            """
            INSERT INTO statistics
            (timestamp, shows_searched, shows_found, shows_not_found,
             episodes_total, episodes_matched, episodes_with_ratings,
             match_types, false_positive_risks)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                datetime.utcnow(),
                summary["shows_searched"],
                summary["shows_found"],
                summary["shows_not_found"],
                summary["episodes_total"],
                summary["episodes_matched"],
                summary["episodes_with_ratings"],
                json.dumps(summary["match_types"]),
                json.dumps(summary["false_positive_risks"]),
            ),
        )
        self.results_conn.commit()

    def close(self) -> None:
        if self.results_conn:
            self.results_conn.close()
        if self.audit_conn:
            self.audit_conn.close()
