"""SQLite catalog of collected documents, with CSV/JSONL export."""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    url TEXT UNIQUE NOT NULL,
    source_id TEXT NOT NULL,
    country TEXT NOT NULL,
    title TEXT,
    page_url TEXT,
    doc_types TEXT,          -- comma-separated: drawing,description,safety,...
    mw_values TEXT,          -- comma-separated MW figures found
    mw_bucket TEXT,          -- <=20 MW / <=50 MW / <=100 MW / <=200 MW / >200 MW
    relevance INTEGER,
    local_path TEXT,
    size_bytes INTEGER,
    fetched_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_documents_country ON documents(country);
CREATE INDEX IF NOT EXISTS idx_documents_bucket ON documents(mw_bucket);
"""


class Catalog:
    def __init__(self, db_path: str | Path):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(SCHEMA)

    def has(self, url: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM documents WHERE url = ?", (url,)
        ).fetchone()
        return row is not None

    def add(
        self,
        *,
        url: str,
        source_id: str,
        country: str,
        title: str,
        page_url: str,
        doc_types: list[str],
        mw_values: list[float],
        mw_bucket: str | None,
        relevance: int,
        local_path: str | None,
        size_bytes: int | None,
    ) -> None:
        self.conn.execute(
            """INSERT OR IGNORE INTO documents
               (url, source_id, country, title, page_url, doc_types,
                mw_values, mw_bucket, relevance, local_path, size_bytes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                url,
                source_id,
                country,
                title,
                page_url,
                ",".join(doc_types),
                ",".join(f"{v:g}" for v in mw_values),
                mw_bucket,
                relevance,
                local_path,
                size_bytes,
            ),
        )
        self.conn.commit()

    def rows(self) -> list[dict]:
        cur = self.conn.execute(
            "SELECT * FROM documents ORDER BY country, source_id, relevance DESC"
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def export_csv(self, path: str | Path) -> int:
        rows = self.rows()
        with open(path, "w", newline="", encoding="utf-8") as fh:
            if not rows:
                fh.write("")
                return 0
            writer = csv.DictWriter(fh, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        return len(rows)

    def export_jsonl(self, path: str | Path) -> int:
        rows = self.rows()
        with open(path, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return len(rows)

    def close(self) -> None:
        self.conn.close()
