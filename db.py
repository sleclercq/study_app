"""
db.py - Database layer for the revision app.

Responsibilities:
  - Create and migrate the SQLite schema (init_db)
  - Seed exercise data from JSON files in the data/ directory (seed_exercises)
  - Provide all query functions used by the UI

Schema overview (see init_db for full DDL):
  exercises  - one row per exercise (e.g. "Latin - Présent de l'indicatif")
  words      - one row per source word (e.g. "aimer"), linked to an exercise
  forms      - one row per conjugated/declined form of a word (e.g. "1re pers. du sing." -> "amo")
  players    - one row per named player (child)
  sessions   - one row per completed 20-question session, linked to player + exercise

Extensibility notes:
  - To add a new exercise (new tense, language, noun cases): drop a JSON file in data/
    matching the schema in seed_exercises(), then re-run seed_exercises(). It is idempotent.
  - To support new quiz types beyond "canonical" and "form", add a type field to the
    questions table if you introduce question persistence, or handle it in main.py's
    question-building logic.
  - Score is stored as REAL (float) to support half-points (0.5 per 2nd/3rd-attempt correct).
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

# Default path for the SQLite database file, next to this module.
_DB_PATH = Path(__file__).parent / "study.db"

# Directory containing JSON seed files for exercises.
_DATA_DIR = Path(__file__).parent / "data"


def _connect(db_path: Path = _DB_PATH) -> sqlite3.Connection:
    """Open a connection with foreign-key enforcement and row_factory for dict-like rows."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row   # rows accessible as row["column_name"]
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------------------
# Migration system
# ---------------------------------------------------------------------------
#
# Each entry in _MIGRATIONS is a SQL script (string) that upgrades the schema
# from the previous version to that version.  The index (0-based) + 1 is the
# target version number, so _MIGRATIONS[0] brings a blank DB to version 1,
# _MIGRATIONS[1] brings version 1 to version 2, etc.
#
# Rules for adding future migrations:
#   1. Append a new string to _MIGRATIONS - never edit existing entries.
#   2. Use ALTER TABLE / CREATE TABLE / CREATE INDEX - never DROP unless you
#      are 100% sure the column/table is unused.
#   3. Keep each migration idempotent where possible (IF NOT EXISTS, etc.).
#   4. The user_version pragma is updated automatically after each script runs.
#
# Schema version is stored in SQLite's built-in PRAGMA user_version (integer).
# A value of 0 means "never versioned" (either a brand-new file or a DB
# created before this migration system was introduced).

_MIGRATIONS: list[str] = [
    # -----------------------------------------------------------------------
    # Migration 1 - initial schema (all tables that existed before versioning)
    # -----------------------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS exercises (
        id   INTEGER PRIMARY KEY AUTOINCREMENT,
        slug TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL
    );

    -- Each word in an exercise.
    -- source    = the prompt shown (e.g. the French word "aimer")
    -- canonical = the primary correct answer (e.g. the Latin infinitive "amare")
    --             For exercises without a canonical (e.g. pure conjugation drills),
    --             set canonical = '' and omit infinitive questions in quiz logic.
    CREATE TABLE IF NOT EXISTS words (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        exercise_id INTEGER NOT NULL REFERENCES exercises(id),
        source      TEXT NOT NULL,
        canonical   TEXT NOT NULL
    );

    -- Conjugated / declined / irregular forms of a word.
    -- label = the label shown to the student (e.g. "1re pers. du singulier")
    -- value = the expected answer (e.g. "amo")
    -- To add a new form type (e.g. "genitif", "passe simple"), just insert rows here;
    -- no schema change required.
    CREATE TABLE IF NOT EXISTS forms (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        word_id INTEGER NOT NULL REFERENCES words(id),
        label   TEXT NOT NULL,
        value   TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS players (
        id   INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    );

    -- score is REAL (float) to store fractional points (1.0 / 0.5 / 0.25 per attempt).
    -- total is the number of questions in the session (may be < SESSION_LENGTH
    -- if the player deselected many verbs).
    CREATE TABLE IF NOT EXISTS sessions (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id   INTEGER NOT NULL REFERENCES players(id),
        exercise_id INTEGER NOT NULL REFERENCES exercises(id),
        played_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
        score       REAL NOT NULL,
        total       INTEGER NOT NULL
    );

    -- Per-player word enable/disable preferences for each exercise.
    -- A missing row means "enabled" (default = all words active).
    -- enabled = 1 (active) or 0 (skipped by this player).
    CREATE TABLE IF NOT EXISTS player_word_prefs (
        player_id INTEGER NOT NULL REFERENCES players(id),
        word_id   INTEGER NOT NULL REFERENCES words(id),
        enabled   INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (player_id, word_id)
    );
    """,
    # -----------------------------------------------------------------------
    # Migration 2 - purge the accord_participe_passe exercise seeded in its
    # first (incomplete) format so it is re-seeded on next startup from the
    # new JSON that stores __case__ / __cod__ metadata in the forms table.
    # Safe: the exercise was brand-new and had no player sessions yet.
    # -----------------------------------------------------------------------
    """
    DELETE FROM player_word_prefs WHERE word_id IN (
        SELECT id FROM words WHERE exercise_id IN (
            SELECT id FROM exercises WHERE slug = 'accord_participe_passe'
        )
    );
    DELETE FROM sessions WHERE exercise_id IN (
        SELECT id FROM exercises WHERE slug = 'accord_participe_passe'
    );
    DELETE FROM forms WHERE word_id IN (
        SELECT id FROM words WHERE exercise_id IN (
            SELECT id FROM exercises WHERE slug = 'accord_participe_passe'
        )
    );
    DELETE FROM words WHERE exercise_id IN (
        SELECT id FROM exercises WHERE slug = 'accord_participe_passe'
    );
    DELETE FROM exercises WHERE slug = 'accord_participe_passe';
    """,
    # -----------------------------------------------------------------------
    # Migration 3 - purge and re-seed accord_participe_passe again: bank
    # expanded from 27 to 100 sentences (25 per grammatical case).
    # -----------------------------------------------------------------------
    """
    DELETE FROM player_word_prefs WHERE word_id IN (
        SELECT id FROM words WHERE exercise_id IN (
            SELECT id FROM exercises WHERE slug = 'accord_participe_passe'
        )
    );
    DELETE FROM sessions WHERE exercise_id IN (
        SELECT id FROM exercises WHERE slug = 'accord_participe_passe'
    );
    DELETE FROM forms WHERE word_id IN (
        SELECT id FROM words WHERE exercise_id IN (
            SELECT id FROM exercises WHERE slug = 'accord_participe_passe'
        )
    );
    DELETE FROM words WHERE exercise_id IN (
        SELECT id FROM exercises WHERE slug = 'accord_participe_passe'
    );
    DELETE FROM exercises WHERE slug = 'accord_participe_passe';
    """,
    # -----------------------------------------------------------------------
    # Migration 4 - purge and re-seed accord_participe_passe: bank expanded
    # from 100 to 200 sentences. avoir_cod_avant now weighted at 80/200 (40%)
    # to reflect the pedagogical focus of the lesson.
    # -----------------------------------------------------------------------
    """
    DELETE FROM player_word_prefs WHERE word_id IN (
        SELECT id FROM words WHERE exercise_id IN (
            SELECT id FROM exercises WHERE slug = 'accord_participe_passe'
        )
    );
    DELETE FROM sessions WHERE exercise_id IN (
        SELECT id FROM exercises WHERE slug = 'accord_participe_passe'
    );
    DELETE FROM forms WHERE word_id IN (
        SELECT id FROM words WHERE exercise_id IN (
            SELECT id FROM exercises WHERE slug = 'accord_participe_passe'
        )
    );
    DELETE FROM words WHERE exercise_id IN (
        SELECT id FROM exercises WHERE slug = 'accord_participe_passe'
    );
    DELETE FROM exercises WHERE slug = 'accord_participe_passe';
    """,
]


def _apply_migrations(db_path: Path = _DB_PATH) -> None:
    """
    Apply any pending schema migrations to the database.

    Uses SQLite's built-in PRAGMA user_version to track which migrations have
    already been applied.  Safe to call on every startup - it is a no-op when
    the DB is already at the latest version.

    Handles legacy databases (created before this system was introduced) by
    detecting existing tables and stamping them at version 1 without re-running
    the DDL.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        current_version = conn.execute("PRAGMA user_version").fetchone()[0]

        if current_version == 0:
            # Check whether the DB already contains our tables (legacy DB created
            # before the migration system existed).  If so, mark it as version 1
            # without re-running migration 1 (all tables already exist).
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='exercises'"
            ).fetchone()
            if row is not None:
                conn.execute(f"PRAGMA user_version = {len(_MIGRATIONS)}")
                conn.commit()
                return

        target_version = len(_MIGRATIONS)
        if current_version >= target_version:
            return  # Already up to date.

        for i in range(current_version, target_version):
            version = i + 1
            # executescript issues an implicit COMMIT before running, so each
            # migration runs in its own transaction.
            conn.executescript(_MIGRATIONS[i])
            conn.execute(f"PRAGMA user_version = {version}")
            conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path = _DB_PATH) -> None:
    """Apply all pending schema migrations.  Safe to call on every startup."""
    _apply_migrations(db_path)


def seed_exercises(db_path: Path = _DB_PATH, data_dir: Path = _DATA_DIR) -> None:
    """
    Load all JSON exercise files from data_dir into the database. Idempotent:
    exercises already present (matched by slug) are skipped; only new words/forms
    are inserted.

    JSON file format (see data/latin_verbs_present.json for a full example):
    {
      "slug": "unique_exercise_id",       # must match across app versions
      "name": "Display name",
      "words": [
        {
          "source": "aimer",              # French (or source language) word
          "canonical": "amare",           # Latin infinitive (or primary answer)
          "forms": [
            {"label": "1re pers. du singulier", "value": "amo"},
            ...
          ]
        },
        ...
      ]
    }

    To add a new exercise: drop a .json file in data/ and restart the app.
    """
    if not data_dir.exists():
        return

    with _connect(db_path) as conn:
        for json_file in sorted(data_dir.glob("*.json")):
            with open(json_file, encoding="utf-8") as f:
                exercise = json.load(f)

            slug = exercise["slug"]
            name = exercise["name"]

            # Check if this exercise is already seeded.
            row = conn.execute(
                "SELECT id FROM exercises WHERE slug = ?", (slug,)
            ).fetchone()

            if row is None:
                # New exercise: insert it.
                cursor = conn.execute(
                    "INSERT INTO exercises (slug, name) VALUES (?, ?)", (slug, name)
                )
                exercise_id = cursor.lastrowid
            else:
                # Already exists: skip re-seeding words/forms to avoid duplicates.
                # If you need to update seed data, delete the exercise row (cascade
                # deletes words/forms) and re-run — or implement a proper migration.
                continue

            for word_data in exercise.get("words", []):
                cursor = conn.execute(
                    "INSERT INTO words (exercise_id, source, canonical) VALUES (?, ?, ?)",
                    (exercise_id, word_data["source"], word_data["canonical"]),
                )
                word_id = cursor.lastrowid

                for form in word_data.get("forms", []):
                    conn.execute(
                        "INSERT INTO forms (word_id, label, value) VALUES (?, ?, ?)",
                        (word_id, form["label"], form["value"]),
                    )


# ---------------------------------------------------------------------------
# Player queries
# ---------------------------------------------------------------------------

def list_players(db_path: Path = _DB_PATH) -> list:
    """Return all players sorted alphabetically. Each dict has 'id' and 'name'."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, name FROM players ORDER BY name COLLATE NOCASE"
        ).fetchall()
    return [dict(r) for r in rows]


def get_or_create_player(name: str, db_path: Path = _DB_PATH) -> dict:  # noqa: E501
    """
    Return the player with the given name, creating one if it doesn't exist.
    Name matching is case-sensitive (children may have same name with different case — unlikely
    but we preserve what they enter). Strip surrounding whitespace before lookup/insert.
    Returns a dict with 'id' and 'name'.
    """
    name = name.strip()
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, name FROM players WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            cursor = conn.execute(
                "INSERT INTO players (name) VALUES (?)", (name,)
            )
            return {"id": cursor.lastrowid, "name": name}
        return dict(row)


# ---------------------------------------------------------------------------
# Exercise queries
# ---------------------------------------------------------------------------

def list_exercises(db_path: Path = _DB_PATH) -> list:
    """
    Return all exercises. Each dict has 'id', 'slug', 'name'.
    Currently the app uses a single exercise; this function is here for future
    exercise-selection screens.
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, slug, name FROM exercises ORDER BY name"
        ).fetchall()
    return [dict(r) for r in rows]


def get_exercise_by_slug(slug: str, db_path: Path = _DB_PATH) -> Optional[dict]:
    """Return the exercise with the given slug, or None if not found."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, slug, name FROM exercises WHERE slug = ?", (slug,)
        ).fetchone()
    return dict(row) if row else None


def get_words_for_exercise(exercise_id: int, db_path: Path = _DB_PATH) -> list:
    """
    Return all words for an exercise as a list of dicts: {id, source, canonical}.
    Used by VerbSelectionScreen to build the checkbox list.
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, source, canonical FROM words WHERE exercise_id = ? ORDER BY rowid",
            (exercise_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_word_prefs(player_id: int, exercise_id: int, db_path: Path = _DB_PATH) -> list:
    """
    Return the enabled/disabled state of every word in an exercise for a given player.
    Words with no preference row default to enabled=True.

    Returns a list of dicts: {word_id, source, enabled (bool)}.
    Ordered by the word's insertion order (same as the JSON seed order).
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            """SELECT w.id AS word_id, w.source,
                      COALESCE(p.enabled, 1) AS enabled
               FROM words w
               LEFT JOIN player_word_prefs p
                      ON p.word_id = w.id AND p.player_id = ?
               WHERE w.exercise_id = ?
               ORDER BY w.rowid""",
            (player_id, exercise_id),
        ).fetchall()
    return [{"word_id": r["word_id"], "source": r["source"], "enabled": bool(r["enabled"])}
            for r in rows]


def save_word_prefs(player_id: int, prefs: dict, db_path: Path = _DB_PATH) -> None:
    """
    Persist per-player word preferences (upsert).

    prefs: dict mapping word_id (int) -> enabled (bool).
    Call this whenever the player changes their verb selection in VerbSelectionScreen.
    Existing rows are updated; new rows are inserted.
    """
    with _connect(db_path) as conn:
        for word_id, enabled in prefs.items():
            conn.execute(
                """INSERT INTO player_word_prefs (player_id, word_id, enabled)
                   VALUES (?, ?, ?)
                   ON CONFLICT(player_id, word_id) DO UPDATE SET enabled = excluded.enabled""",
                (player_id, int(word_id), 1 if enabled else 0),
            )


def get_questions_for_exercise(
    exercise_id: int,
    enabled_word_ids: Optional[list] = None,
    db_path: Path = _DB_PATH,
) -> list:
    """
    Build the question pool for an exercise. Returns a list of question dicts.

    enabled_word_ids: if provided, only include questions for words whose id is in
    this list. Pass None to include all words (e.g. for testing or exercises without
    per-word selection).

    Each question dict has:
      type        : "canonical" | "form"
      prompt      : string shown to the student
      answer      : expected answer (case-insensitive comparison in quiz logic)
      word_source : the source word (for display context)

    Question types:
      "canonical" - student must give the canonical form (e.g. Latin infinitive)
      "form"      - student must give a specific conjugated/declined form

    To add a new question type in the future:
      1. Define a new type string (e.g. "reverse" for Latin -> French).
      2. Build the prompt/answer here and add a branch.
      3. No DB change required.
    """
    with _connect(db_path) as conn:
        words = conn.execute(
            "SELECT id, source, canonical FROM words WHERE exercise_id = ? ORDER BY rowid",
            (exercise_id,),
        ).fetchall()

    # Filter to enabled words if a selection was provided.
    enabled_set = set(enabled_word_ids) if enabled_word_ids is not None else None

    questions = []
    for word in words:
        word_id = word["id"]
        if enabled_set is not None and word_id not in enabled_set:
            continue

        source = word["source"]
        canonical = word["canonical"]

        # Canonical question (e.g. "Comment dit-on 'aimer' en latin ?")
        if canonical:
            questions.append({
                "type": "canonical",
                "prompt": f"Comment dit-on \u00ab\u00a0{source}\u00a0\u00bb en latin\u00a0?",
                "answer": canonical,
                "word_source": source,
            })

        # One question per conjugated/declined form.
        with _connect(db_path) as conn2:
            forms = conn2.execute(
                "SELECT label, value FROM forms WHERE word_id = ?", (word_id,)
            ).fetchall()

        for form in forms:
            questions.append({
                "type": "form",
                "prompt": f"\u00ab\u00a0{source}\u00a0\u00bb \u2014 {form['label']}",
                "answer": form["value"],
                "word_source": source,
            })

    return questions


# ---------------------------------------------------------------------------
# English irregular-verb question builder
# ---------------------------------------------------------------------------

def get_english_questions_for_exercise(
    exercise_id: int,
    enabled_word_ids: Optional[list] = None,
    db_path: Path = _DB_PATH,
) -> list:
    """
    Build the question pool for an English irregular-verbs exercise.
    Each word produces one question dict with all three forms:
      source        : French prompt shown to the student
      base          : expected base form (e.g. "go")
      preterit      : expected preterit (e.g. "went")
      past_participle: expected past participle (e.g. "gone")
      type          : "english_irregular"

    Relies on the JSON seed having exactly three forms per word with labels
    "base verbale", "prétérit", and "participe passé".
    """
    with _connect(db_path) as conn:
        words = conn.execute(
            "SELECT id, source FROM words WHERE exercise_id = ? ORDER BY rowid",
            (exercise_id,),
        ).fetchall()

    enabled_set = set(enabled_word_ids) if enabled_word_ids is not None else None

    questions = []
    for word in words:
        word_id = word["id"]
        if enabled_set is not None and word_id not in enabled_set:
            continue

        with _connect(db_path) as conn2:
            forms = conn2.execute(
                "SELECT label, value FROM forms WHERE word_id = ?", (word_id,)
            ).fetchall()

        forms_dict = {f["label"]: f["value"] for f in forms}
        questions.append({
            "type": "english_irregular",
            "source": word["source"],
            "base": forms_dict.get("base verbale", ""),
            "preterit": forms_dict.get("prétérit", ""),
            "past_participle": forms_dict.get("participe passé", ""),
        })

    return questions


# ---------------------------------------------------------------------------
# Fill-in-the-blank question builder
# ---------------------------------------------------------------------------

def get_fill_blank_questions(
    exercise_id: int,
    db_path: Path = _DB_PATH,
) -> list:
    """
    Build the question pool for a fill-in-the-blank exercise.
    Each sentence is stored as a word row: source = sentence text, canonical = answer.

    Returns a list of dicts compatible with QuizScreen:
      type   : "fill_blank"
      prompt : the full sentence with _____ and verb hint in parentheses
      answer : the expected irregular form (e.g. "bought")
    """
    with _connect(db_path) as conn:
        words = conn.execute(
            "SELECT source, canonical FROM words WHERE exercise_id = ? ORDER BY rowid",
            (exercise_id,),
        ).fetchall()

    return [
        {
            "type": "fill_blank",
            "prompt": word["source"],
            "answer": word["canonical"],
        }
        for word in words
    ]


# ---------------------------------------------------------------------------
# Accord du participe passé question builder
# ---------------------------------------------------------------------------

def get_accord_pp_questions(
    exercise_id: int,
    db_path: Path = _DB_PATH,
) -> list:
    """
    Build the question pool for the 'accord du participe passé' exercise.

    Each sentence (stored as a word row) produces one question dict:
      type       : "accord_pp"
      prompt     : full sentence with _____ blank and (infinitif) hint
      answer     : expected past participle (canonical field)
      case       : grammatical case — one of:
                     "sans_auxiliaire"  ppé without auxiliary → agrees like adjective
                     "avec_etre"        ppé with ÊTRE → agrees with subject
                     "avoir_cod_apres"  ppé with AVOIR, COD after verb → no agreement
                     "avoir_cod_avant"  ppé with AVOIR, COD before verb → agrees with COD
      cod        : text of the COD to identify (avoir_cod_avant only, else "")
                   Matches the exact token(s) the student must click in the sentence.

    Grammar metadata is stored in the forms table under special labels:
      __case__ → the case identifier string
      __cod__  → the COD text (empty for cases other than avoir_cod_avant)
    """
    with _connect(db_path) as conn:
        words = conn.execute(
            "SELECT id, source, canonical FROM words "
            "WHERE exercise_id = ? ORDER BY rowid",
            (exercise_id,),
        ).fetchall()

    questions = []
    for word in words:
        word_id = word["id"]
        with _connect(db_path) as conn2:
            forms = conn2.execute(
                "SELECT label, value FROM forms WHERE word_id = ?", (word_id,)
            ).fetchall()

        meta = {f["label"]: f["value"] for f in forms}
        questions.append({
            "type":   "accord_pp",
            "prompt": word["source"],
            "answer": word["canonical"],
            "case":   meta.get("__case__", ""),
            "cod":    meta.get("__cod__",  ""),
        })

    return questions


# ---------------------------------------------------------------------------
# Session queries
# ---------------------------------------------------------------------------

def save_session(
    player_id: int,
    exercise_id: int,
    score: float,
    total: int,
    db_path: Path = _DB_PATH,
) -> int:
    """
    Persist a completed session. Returns the new session id.

    score: float, supports half-points (e.g. 17.5 out of 20).
    total: number of questions (currently always 20, kept flexible).
    """
    with _connect(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO sessions (player_id, exercise_id, score, total)
               VALUES (?, ?, ?, ?)""",
            (player_id, exercise_id, score, total),
        )
    return cursor.lastrowid


def get_history(
    player_id: int,
    exercise_id: int,
    db_path: Path = _DB_PATH,
) -> list:
    """
    Return all sessions for this player + exercise, newest first.
    No cap: the UI scrolls through however many sessions exist.

    Each dict: {id, played_at (ISO string), score, total, percent}
    percent = score/total*100, pre-computed for display convenience.
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            """SELECT id, played_at, score, total
               FROM sessions
               WHERE player_id = ? AND exercise_id = ?
               ORDER BY played_at DESC, id DESC""",
            (player_id, exercise_id),
        ).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        d["percent"] = round(d["score"] / d["total"] * 100) if d["total"] else 0
        result.append(d)
    return result


# ---------------------------------------------------------------------------
# Bootstrap helper called at app startup
# ---------------------------------------------------------------------------

def bootstrap(db_path: Path = _DB_PATH, data_dir: Path = _DATA_DIR) -> None:
    """
    One-call setup: create schema then seed any new exercises.
    Call this once at the very start of main.py before showing any UI.
    """
    init_db(db_path)
    seed_exercises(db_path, data_dir)
