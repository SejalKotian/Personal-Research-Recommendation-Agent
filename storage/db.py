"""
SQLite memory store.

Tables:
  paper_history  — every paper ever recommended, to avoid duplicates
  digest_runs    — log of each weekly run + serialized output
  feedback       — user feedback per paper (useful / not_relevant / too_theoretical)
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

import config


@contextmanager
def _conn():
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db() -> None:
    """Create tables if they don't exist. Call once at startup."""
    with _conn() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS paper_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                url         TEXT UNIQUE NOT NULL,
                arxiv_id    TEXT,
                title       TEXT NOT NULL,
                date        TEXT,
                source      TEXT,
                seen_on     TEXT NOT NULL   -- ISO date of the run that surfaced it
            );

            CREATE TABLE IF NOT EXISTS digest_runs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                run_at          TEXT NOT NULL,
                lookback_days   INTEGER,
                profile_json    TEXT,
                digest_json     TEXT
            );

            CREATE TABLE IF NOT EXISTS feedback (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_url   TEXT NOT NULL,
                rating      TEXT NOT NULL,   -- 'useful' | 'not_relevant' | 'too_theoretical'
                given_at    TEXT NOT NULL
            );
            """
        )


def get_seen_urls() -> set[str]:
    """Return the set of all paper URLs previously recommended."""
    with _conn() as con:
        rows = con.execute("SELECT url FROM paper_history").fetchall()
    return {row["url"] for row in rows}


def save_recommended_papers(papers_dicts: list[dict], run_date: Optional[str] = None) -> None:
    """
    Persist papers from a run so future runs can deduplicate.
    papers_dicts: list of dicts with keys url, arxiv_id, title, date, source
    """
    today = run_date or datetime.now().strftime("%Y-%m-%d")
    with _conn() as con:
        for p in papers_dicts:
            con.execute(
                """
                INSERT OR IGNORE INTO paper_history
                    (url, arxiv_id, title, date, source, seen_on)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    p.get("url", ""),
                    p.get("arxiv_id"),
                    p.get("title", ""),
                    p.get("date", ""),
                    p.get("source", ""),
                    today,
                ),
            )


def log_digest_run(profile_dict: dict, digest_dict: dict, lookback_days: int) -> int:
    """
    Save a full run record. Returns the new run ID.
    """
    with _conn() as con:
        cur = con.execute(
            """
            INSERT INTO digest_runs (run_at, lookback_days, profile_json, digest_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(),
                lookback_days,
                json.dumps(profile_dict),
                json.dumps(digest_dict),
            ),
        )
        return cur.lastrowid


def save_feedback(paper_url: str, rating: str) -> None:
    """
    Record user feedback. rating must be 'useful', 'not_relevant', or 'too_theoretical'.
    """
    valid = {"useful", "not_relevant", "too_theoretical"}
    if rating not in valid:
        raise ValueError(f"rating must be one of {valid}")
    with _conn() as con:
        con.execute(
            "INSERT INTO feedback (paper_url, rating, given_at) VALUES (?, ?, ?)",
            (paper_url, rating, datetime.now().isoformat()),
        )


def get_recent_runs(limit: int = 10) -> list[dict]:
    """Return the most recent N digest runs as plain dicts."""
    with _conn() as con:
        rows = con.execute(
            "SELECT id, run_at, lookback_days FROM digest_runs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_run_digest(run_id: int) -> Optional[dict]:
    """Return the full digest JSON for a run, or None if not found."""
    with _conn() as con:
        row = con.execute(
            "SELECT digest_json FROM digest_runs WHERE id = ?", (run_id,)
        ).fetchone()
    if row:
        return json.loads(row["digest_json"])
    return None
