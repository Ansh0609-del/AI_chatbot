-- schema.sql — AI Study Assistant database schema
-- This file is a human-readable reference. The application creates these
-- tables automatically at runtime via database.py:init_db(), so you do NOT
-- need to run this file manually. It's provided for documentation and for
-- anyone who wants to inspect or recreate the schema by hand.

-- Users: one row per study profile (no passwords — local single-machine app)
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    last_active TEXT DEFAULT (datetime('now'))
);

-- Topics: one row per topic a user has studied (explanation + notes cached)
CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    topic TEXT NOT NULL,
    explanation TEXT,
    notes TEXT,
    studied_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Quiz results: one row per quiz attempt, linked back to the topic studied
CREATE TABLE IF NOT EXISTS quiz_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    topic_id INTEGER NOT NULL,
    topic TEXT NOT NULL,
    questions TEXT NOT NULL,        -- JSON array of question strings
    answers TEXT NOT NULL,          -- JSON array of the user's chosen letters
    correct_answers TEXT NOT NULL,  -- JSON array of correct letters
    score INTEGER NOT NULL,         -- number correct
    total INTEGER DEFAULT 5,        -- number of questions (always 5 by default)
    feedback TEXT,                  -- AI-generated feedback text
    taken_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (topic_id) REFERENCES topics(id)
);

-- Weak topics: auto-flagged whenever a quiz score is <= 2/5
CREATE TABLE IF NOT EXISTS weak_topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    topic TEXT NOT NULL,
    times_flagged INTEGER DEFAULT 1,
    last_flagged TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Chat history: persisted so the chatbot has memory across page reloads
CREATE TABLE IF NOT EXISTS chat_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,             -- 'user' or 'assistant'
    content TEXT NOT NULL,
    timestamp TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);
