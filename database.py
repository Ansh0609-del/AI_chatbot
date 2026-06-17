# database.py - SQLite database layer for AI Study Assistant
# Handles all database operations: schema creation, CRUD for users, topics, quizzes, chat history

import logging
import os
import sqlite3
import json
from datetime import datetime

logger = logging.getLogger(__name__)

# Configurable via env var so deployment platforms (e.g. Render) can point this
# at a persistent disk mount. Defaults to a local file for development.
# NOTE: Render's free-tier filesystem is ephemeral (wiped on redeploy/restart),
# so for real persistence in production, attach a Render Disk and set
# DATABASE_PATH to a path inside that mount (see render.yaml).
DB_PATH = os.environ.get("DATABASE_PATH", "study_assistant.db")


def get_connection():
    """Return a SQLite connection with row_factory for dict-like access."""
    # Ensure the parent directory exists (relevant when DATABASE_PATH points
    # into a mounted disk like /var/data/study_assistant.db).
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL mode allows concurrent readers + a writer, which matters once
    # Gunicorn runs multiple worker processes against the same SQLite file.
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db():
    """Create all tables on first run. Safe to call repeatedly (uses IF NOT EXISTS)."""
    conn = get_connection()
    cursor = conn.cursor()

    # Users table — stores name and metadata
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            last_active TEXT DEFAULT (datetime('now'))
        )
    """)

    # Topics studied — one row per study session for a topic
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            topic TEXT NOT NULL,
            explanation TEXT,
            notes TEXT,
            studied_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # Quiz results — one row per quiz attempt
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS quiz_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            topic_id INTEGER NOT NULL,
            topic TEXT NOT NULL,
            questions TEXT NOT NULL,      -- JSON array of question strings
            answers TEXT NOT NULL,         -- JSON array of user answers
            correct_answers TEXT NOT NULL, -- JSON array of correct answers
            score INTEGER NOT NULL,        -- number correct out of 5
            total INTEGER DEFAULT 5,
            feedback TEXT,                 -- AI feedback on performance
            taken_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (topic_id) REFERENCES topics(id)
        )
    """)

    # Weak topics — derived from low quiz scores
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS weak_topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            topic TEXT NOT NULL,
            times_flagged INTEGER DEFAULT 1,
            last_flagged TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # Chat history — persists conversation context per user
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,            -- 'user' or 'assistant'
            content TEXT NOT NULL,
            timestamp TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    conn.commit()
    conn.close()
    logger.info("Database initialized successfully at %s", DB_PATH)


# ─── User operations ────────────────────────────────────────────────────────

def create_user(name: str) -> int:
    """Insert a new user and return their id."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO users (name) VALUES (?)", (name,))
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return user_id


def get_user(user_id: int) -> dict | None:
    """Fetch a user by id, returns dict or None."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_users() -> list[dict]:
    """Return all users as a list of dicts."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM users ORDER BY last_active DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_user_activity(user_id: int):
    """Bump last_active timestamp for a user."""
    conn = get_connection()
    conn.execute(
        "UPDATE users SET last_active = datetime('now') WHERE id = ?", (user_id,)
    )
    conn.commit()
    conn.close()


# ─── Topic operations ────────────────────────────────────────────────────────

def save_topic(user_id: int, topic: str, explanation: str, notes: str) -> int:
    """Store a studied topic and return its id."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO topics (user_id, topic, explanation, notes) VALUES (?, ?, ?, ?)",
        (user_id, topic, explanation, notes),
    )
    topic_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return topic_id


def get_user_topics(user_id: int) -> list[dict]:
    """Return all topics a user has studied, newest first."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM topics WHERE user_id = ? ORDER BY studied_at DESC", (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Quiz operations ─────────────────────────────────────────────────────────

def save_quiz_result(
    user_id: int,
    topic_id: int,
    topic: str,
    questions: list,
    answers: list,
    correct_answers: list,
    score: int,
    feedback: str,
) -> int:
    """Persist quiz result and flag topic as weak if score ≤ 2."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO quiz_results
           (user_id, topic_id, topic, questions, answers, correct_answers, score, feedback)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            user_id,
            topic_id,
            topic,
            json.dumps(questions),
            json.dumps(answers),
            json.dumps(correct_answers),
            score,
            feedback,
        ),
    )
    result_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # Automatically flag weak topic if score is low
    if score <= 2:
        flag_weak_topic(user_id, topic)

    return result_id


def get_user_quiz_results(user_id: int) -> list[dict]:
    """Return all quiz results for a user, newest first."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM quiz_results WHERE user_id = ? ORDER BY taken_at DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["questions"] = json.loads(d["questions"])
        d["answers"] = json.loads(d["answers"])
        d["correct_answers"] = json.loads(d["correct_answers"])
        results.append(d)
    return results


def get_topic_quiz_history(user_id: int, topic: str) -> list[dict]:
    """Return all quiz attempts for a specific topic."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM quiz_results WHERE user_id = ? AND topic = ? ORDER BY taken_at",
        (user_id, topic),
    ).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["questions"] = json.loads(d["questions"])
        d["answers"] = json.loads(d["answers"])
        d["correct_answers"] = json.loads(d["correct_answers"])
        results.append(d)
    return results


# ─── Weak topic operations ───────────────────────────────────────────────────

def flag_weak_topic(user_id: int, topic: str):
    """Insert or increment a weak topic entry."""
    conn = get_connection()
    existing = conn.execute(
        "SELECT id FROM weak_topics WHERE user_id = ? AND topic = ?",
        (user_id, topic),
    ).fetchone()
    if existing:
        conn.execute(
            """UPDATE weak_topics
               SET times_flagged = times_flagged + 1, last_flagged = datetime('now')
               WHERE id = ?""",
            (existing["id"],),
        )
    else:
        conn.execute(
            "INSERT INTO weak_topics (user_id, topic) VALUES (?, ?)",
            (user_id, topic),
        )
    conn.commit()
    conn.close()


def get_weak_topics(user_id: int) -> list[dict]:
    """Return weak topics for a user, most frequently flagged first."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM weak_topics WHERE user_id = ? ORDER BY times_flagged DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Chat history operations ─────────────────────────────────────────────────

def save_chat_message(user_id: int, role: str, content: str):
    """Append a single message to chat history."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)",
        (user_id, role, content),
    )
    conn.commit()
    conn.close()


def get_chat_history(user_id: int, limit: int = 20) -> list[dict]:
    """Return the most recent N messages for context building (oldest first)."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT role, content FROM chat_history
           WHERE user_id = ?
           ORDER BY id DESC LIMIT ?""",
        (user_id, limit),
    ).fetchall()
    conn.close()
    # Reverse so oldest message is first (for LLM context)
    return [dict(r) for r in reversed(rows)]


def clear_chat_history(user_id: int):
    """Wipe chat history for a user (fresh start)."""
    conn = get_connection()
    conn.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


# ─── Dashboard / analytics helpers ───────────────────────────────────────────

def get_dashboard_data(user_id: int) -> dict:
    """Aggregate stats for the dashboard view."""
    conn = get_connection()

    topics_studied = conn.execute(
        "SELECT COUNT(*) as cnt FROM topics WHERE user_id = ?", (user_id,)
    ).fetchone()["cnt"]

    quiz_stats = conn.execute(
        """SELECT COUNT(*) as attempts,
                  AVG(CAST(score AS REAL) / total * 100) as avg_score,
                  MAX(CAST(score AS REAL) / total * 100) as best_score
           FROM quiz_results WHERE user_id = ?""",
        (user_id,),
    ).fetchone()

    recent_quizzes = conn.execute(
        """SELECT topic, score, total,
                  CAST(score AS REAL) / total * 100 as pct,
                  taken_at
           FROM quiz_results WHERE user_id = ?
           ORDER BY taken_at DESC LIMIT 10""",
        (user_id,),
    ).fetchall()

    weak = conn.execute(
        "SELECT topic, times_flagged FROM weak_topics WHERE user_id = ? ORDER BY times_flagged DESC LIMIT 5",
        (user_id,),
    ).fetchall()

    conn.close()

    return {
        "topics_studied": topics_studied,
        "quiz_attempts": quiz_stats["attempts"] or 0,
        "avg_score": round(quiz_stats["avg_score"] or 0, 1),
        "best_score": round(quiz_stats["best_score"] or 0, 1),
        "recent_quizzes": [dict(r) for r in recent_quizzes],
        "weak_topics": [dict(r) for r in weak],
    }
