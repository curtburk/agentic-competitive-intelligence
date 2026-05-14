"""
competitive_intel/state.py
Trace storage in SQLite. Brief state lives in the wiki.
"""

import os
import sqlite3
import json
from pathlib import Path

WIKI_ROOT = Path(os.environ.get("WIKI_ROOT", "/data/wiki"))
DB_PATH = Path(os.environ.get("TRACE_DB_PATH", "/data/traces.db"))


def _get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB_PATH))
    db.execute("""
        CREATE TABLE IF NOT EXISTS traces (
            run_id TEXT NOT NULL,
            trace_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    db.commit()
    return db


def save_trace(run_id: str, traces: list[dict]):
    db = _get_db()
    db.execute(
        "INSERT INTO traces (run_id, trace_json) VALUES (?, ?)",
        (run_id, json.dumps(traces))
    )
    db.commit()
    db.close()


def load_traces(run_id: str) -> list[dict] | None:
    db = _get_db()
    row = db.execute(
        "SELECT trace_json FROM traces WHERE run_id = ?", (run_id,)
    ).fetchone()
    db.close()
    if row:
        return json.loads(row[0])
    return None


def load_previous_brief_summary() -> str:
    """
    Read the most recent weekly brief from the wiki and extract
    the executive summary for the recurrence loop.
    """
    briefs_dir = WIKI_ROOT / "briefs"
    if not briefs_dir.exists():
        return "First run."

    brief_files = sorted(briefs_dir.glob("*.md"), reverse=True)
    if not brief_files:
        return "First run."

    text = brief_files[0].read_text()
    in_summary = False
    summary_lines = []
    for line in text.split("\n"):
        if line.strip() == "## Executive Summary":
            in_summary = True
            continue
        if in_summary and line.startswith("## "):
            break
        if in_summary and line.strip():
            summary_lines.append(line.strip())

    return " ".join(summary_lines) if summary_lines else "First run."
