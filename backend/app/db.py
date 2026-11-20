"""SQLite access with numbered, append-only migrations.

To change the schema, append a new entry to MIGRATIONS. Never edit an applied one.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

MIGRATIONS: list[str] = [
    # 1 — initial schema
    """
    CREATE TABLE books (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        author TEXT NOT NULL DEFAULT '',
        source_filename TEXT NOT NULL,
        source_path TEXT NOT NULL,          -- original manuscript, never modified
        source_sha256 TEXT NOT NULL,
        source_format TEXT NOT NULL,
        cover_path TEXT,
        narration_profile_id INTEGER REFERENCES narration_profiles(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE chapters (
        id INTEGER PRIMARY KEY,
        book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        title TEXT NOT NULL,
        text TEXT NOT NULL,                 -- paragraphs separated by blank lines
        word_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_chapters_book ON chapters(book_id, position);

    CREATE TABLE narration_profiles (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        voice TEXT NOT NULL,
        style_key TEXT NOT NULL DEFAULT 'natural',
        pace TEXT NOT NULL DEFAULT 'natural',
        language TEXT,
        delivery_notes TEXT NOT NULL DEFAULT '',
        output_format TEXT NOT NULL DEFAULT 'mp3',
        is_default INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE characters (
        id INTEGER PRIMARY KEY,
        book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        -- Future: character-specific voices. Unused by the v1 pipeline.
        voice TEXT,
        style TEXT
    );

    CREATE TABLE pronunciations (
        id INTEGER PRIMARY KEY,
        book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        chapter_id INTEGER REFERENCES chapters(id) ON DELETE CASCADE,  -- NULL = book-wide
        term TEXT NOT NULL,
        replacement TEXT NOT NULL,
        notes TEXT NOT NULL DEFAULT '',
        case_sensitive INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE audio_assets (
        cache_key TEXT PRIMARY KEY,         -- sha256 of every input that affects audio
        path TEXT NOT NULL,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        voice TEXT NOT NULL,
        is_demo INTEGER NOT NULL DEFAULT 0,
        duration_s REAL NOT NULL,
        sample_rate INTEGER NOT NULL,
        channels INTEGER NOT NULL,
        input_tokens INTEGER,
        output_tokens INTEGER,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE segments (
        id INTEGER PRIMARY KEY,
        chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        source_text TEXT NOT NULL,          -- exact manuscript text
        tts_text TEXT NOT NULL,             -- text sent to the provider
        replacements TEXT NOT NULL DEFAULT '[]',  -- JSON map tts_text -> source_text
        analysis TEXT NOT NULL DEFAULT '{}',      -- JSON passage analysis
        style_instruction TEXT NOT NULL DEFAULT '',
        paragraph_start INTEGER NOT NULL,
        paragraph_end INTEGER NOT NULL,
        variant INTEGER NOT NULL DEFAULT 0,       -- bumped to force a fresh take
        cache_key TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',   -- pending|processing|completed|failed|cancelled
        attempts INTEGER NOT NULL DEFAULT 0,
        error TEXT,
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(chapter_id, position)
    );
    CREATE INDEX idx_segments_status ON segments(status);

    CREATE TABLE chapter_audio (
        chapter_id INTEGER PRIMARY KEY REFERENCES chapters(id) ON DELETE CASCADE,
        fingerprint TEXT NOT NULL,          -- hash of ordered segment cache keys
        master_path TEXT NOT NULL,          -- FLAC, lossless
        mp3_path TEXT NOT NULL,
        duration_s REAL NOT NULL,
        is_demo INTEGER NOT NULL DEFAULT 0,
        narrator TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE jobs (
        id INTEGER PRIMARY KEY,
        book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
        profile_id INTEGER REFERENCES narration_profiles(id) ON DELETE SET NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        total_segments INTEGER NOT NULL DEFAULT 0,
        completed_segments INTEGER NOT NULL DEFAULT 0,
        failed_segments INTEGER NOT NULL DEFAULT 0,
        reused_segments INTEGER NOT NULL DEFAULT 0,
        error TEXT,
        cancel_requested INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        started_at TEXT,
        finished_at TEXT
    );
    CREATE INDEX idx_jobs_status ON jobs(status);

    CREATE TABLE usage_log (
        id INTEGER PRIMARY KEY,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        kind TEXT NOT NULL,                 -- segment|preview
        characters INTEGER NOT NULL,
        input_tokens INTEGER,
        output_tokens INTEGER,
        audio_seconds REAL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE listening_progress (
        book_id INTEGER PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
        chapter_id INTEGER REFERENCES chapters(id) ON DELETE SET NULL,
        position_s REAL NOT NULL DEFAULT 0,
        playback_rate REAL NOT NULL DEFAULT 1.0,
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE bookmarks (
        id INTEGER PRIMARY KEY,
        book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
        position_s REAL NOT NULL,
        label TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE app_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
]


class Database:
    """One connection per thread; WAL mode so the worker and API can share the file."""

    def __init__(self, path: Path):
        self.path = path
        self._local = threading.local()

    def connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA busy_timeout = 30000")
            self._local.conn = conn
        return conn

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise

    def query(self, sql: str, params: tuple | dict = ()) -> list[dict]:
        return [dict(r) for r in self.connect().execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple | dict = ()) -> dict | None:
        row = self.connect().execute(sql, params).fetchone()
        return dict(row) if row else None

    def execute(self, sql: str, params: tuple | dict = ()) -> int:
        with self.tx() as conn:
            cur = conn.execute(sql, params)
            return cur.lastrowid

    def migrate(self) -> int:
        conn = self.connect()
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        current = row[0] or 0
        for i, sql in enumerate(MIGRATIONS[current:], start=current + 1):
            conn.executescript("BEGIN;" + sql + f"; INSERT INTO schema_version VALUES ({i}); COMMIT;")
        return len(MIGRATIONS)

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None
