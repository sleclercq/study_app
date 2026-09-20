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
  sessions   - one row per completed session (up to 20 questions), player + exercise
  player_word_prefs - which words a given player has ticked for an exercise

Extensibility notes:
  - To add an exercise: drop a JSON file in data/ (format documented on
    seed_exercises) and restart. Seeding is idempotent AND incremental: adding
    words to an existing file appends them without touching scores or prefs.
  - An exercise carries its own metadata (level, kind, colour, prompt wording).
    `kind` tells main.py which screen and which question builder to use, so a new
    exercise of an existing family needs no Python change at all.
  - Score is stored as REAL (float) to support fractional points (1.0/0.5/0.25).
  - Reserved form labels: a row in `forms` whose label starts and ends with "__"
    is metadata, not a question (__case__/__cod__ for the participe passé,
    __alt_source__/__alt_target__ for accepted synonyms).
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
    # -----------------------------------------------------------------------
    # Migration 5 - exercise metadata + per-word theme (rentrée 4e).
    #
    # Before this version, everything that describes an exercise (which screen
    # runs it, how prompts are worded, where its button goes on the menu) was
    # hardcoded in main.py.  These columns move that description into the DB,
    # fed from the JSON seed files on every startup by _sync_exercise_meta().
    #
    # Strictly additive: existing rows keep their data and take the defaults
    # below until the next seeding pass refreshes them.
    #   level       - school year the exercise belongs to ("4e", "5e")
    #   kind        - question builder + screen to use (see _KINDS in main.py)
    #   sort_order  - position inside its level on the menu
    #   *_language  - display names used by the direction chooser
    #   *_lang_code - "fr" / "de" / ... drives answer tolerance (see answers.py)
    #   prompt_*    - templates for the question wording
    #   words.theme - vocabulary chapter ("Die Familie"), "" for other kinds
    # -----------------------------------------------------------------------
    """
    ALTER TABLE exercises ADD COLUMN level            TEXT    NOT NULL DEFAULT '';
    ALTER TABLE exercises ADD COLUMN kind             TEXT    NOT NULL DEFAULT 'forms';
    ALTER TABLE exercises ADD COLUMN sort_order       INTEGER NOT NULL DEFAULT 100;
    ALTER TABLE exercises ADD COLUMN color            TEXT    NOT NULL DEFAULT '#4a7c59';
    ALTER TABLE exercises ADD COLUMN button_label     TEXT    NOT NULL DEFAULT '';
    ALTER TABLE exercises ADD COLUMN source_language  TEXT    NOT NULL DEFAULT '';
    ALTER TABLE exercises ADD COLUMN target_language  TEXT    NOT NULL DEFAULT '';
    ALTER TABLE exercises ADD COLUMN source_lang_code TEXT    NOT NULL DEFAULT '';
    ALTER TABLE exercises ADD COLUMN target_lang_code TEXT    NOT NULL DEFAULT '';
    ALTER TABLE exercises ADD COLUMN prompt_canonical TEXT    NOT NULL DEFAULT '';
    ALTER TABLE exercises ADD COLUMN prompt_form      TEXT    NOT NULL DEFAULT '';
    ALTER TABLE exercises ADD COLUMN prompt_reverse   TEXT    NOT NULL DEFAULT '';
    ALTER TABLE words     ADD COLUMN theme            TEXT    NOT NULL DEFAULT '';
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

        # A database at version 0 is either brand new or predates this system.
        # Both cases are handled by simply running every migration in order:
        # migration 1 is CREATE TABLE IF NOT EXISTS throughout, so it is a no-op
        # on a legacy file, and the later ones are additive.  (Earlier versions
        # of this function stamped legacy files at the latest version without
        # running anything, which silently skipped the columns added since.)

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


# Exercise-level metadata read from each JSON seed file.  Key = column name in
# the exercises table, value = (JSON key, default).  Everything here is refreshed
# on every startup, so editing a JSON file is enough to change how an exercise is
# worded or where its button sits - no migration, no DB surgery.
_EXERCISE_META: dict = {
    "level":            ("level",            ""),
    "kind":             ("kind",             "forms"),
    "sort_order":       ("sort_order",        100),
    "color":            ("color",            "#4a7c59"),
    "button_label":     ("button_label",     ""),
    "source_language":  ("source_language",  ""),
    "target_language":  ("target_language",  ""),
    "source_lang_code": ("source_lang_code", ""),
    "target_lang_code": ("target_lang_code", ""),
    "prompt_canonical": ("canonical_prompt", ""),
    "prompt_form":      ("form_prompt",      ""),
    "prompt_reverse":   ("reverse_prompt",   ""),
}


def _sync_exercise_meta(conn, exercise_id: int, exercise: dict) -> None:
    """Refresh the name + presentation metadata of an exercise from its JSON."""
    values = {col: exercise.get(key, default) for col, (key, default) in _EXERCISE_META.items()}
    values["button_label"] = values["button_label"] or exercise["name"]
    assignments = ", ".join(f"{col} = ?" for col in values)
    conn.execute(
        f"UPDATE exercises SET name = ?, {assignments} WHERE id = ?",
        [exercise["name"], *values.values(), exercise_id],
    )


def _word_meta_forms(word_data: dict) -> list:
    """
    Turn the human-friendly keys of a word into rows for the forms table.

    Besides the explicit "forms" list, a word may carry:
      alt_target : other accepted answers in the target language (German, Latin...)
      alt_source : other accepted answers in the source language (French)
    They are stored as forms rows under the reserved labels __alt_target__ /
    __alt_source__, the same trick already used by accord_participe_passe
    (__case__ / __cod__).  No schema change needed to accept a new synonym.
    """
    rows = list(word_data.get("forms", []))
    for key, label in (("alt_target", "__alt_target__"), ("alt_source", "__alt_source__")):
        for value in word_data.get(key, []):
            rows.append({"label": label, "value": value})
    return rows


def seed_exercises(db_path: Path = _DB_PATH, data_dir: Path = _DATA_DIR) -> None:
    """
    Load every JSON exercise file from data_dir into the database.

    Idempotent and incremental - safe to run on every startup:
      - a new slug creates the exercise;
      - an existing exercise keeps its id, its sessions and its player prefs,
        and only has its metadata refreshed;
      - words already in the DB (matched on source + canonical) are left alone,
        words present in the JSON but not in the DB are appended.

    That last point is what lets a vocabulary list grow through the year: add a
    new "Leçon 7" block at the end of data/allemand_vocabulaire.json, relaunch,
    and the new words are simply there - nobody loses a score.

    JSON file format (see data/allemand_vocabulaire.json for a full example):
    {
      "slug": "unique_exercise_id",       # must never change across versions
      "name": "Display name",
      "level": "4e",                      # section of the menu
      "kind": "vocab",                    # question builder + screen
      "sort_order": 10,                   # position inside the section
      "color": "#8a6a2a",                 # menu button colour
      "button_label": "Two-line\nmenu label",
      "source_language": "Français", "source_lang_code": "fr",
      "target_language": "Allemand",  "target_lang_code": "de",
      "canonical_prompt": "Traduis en allemand : « {source} »",
      "reverse_prompt":   "Traduis en français : « {canonical} »",
      "form_prompt":      "« {source} » — {label}",
      "words": [
        {
          "theme": "Die Familie — La famille",   # vocab only, groups the checkboxes
          "source": "le père",                   # French (source language)
          "canonical": "der Vater",              # expected translation
          "alt_source": ["le papa"],             # other accepted French answers
          "alt_target": [],                      # other accepted German answers
          "forms": [{"label": "pluriel", "value": "die Väter"}]
        }
      ]
    }

    To add a whole new exercise: drop a .json file in data/ and restart the app.
    """
    if not data_dir.exists():
        return

    with _connect(db_path) as conn:
        for json_file in sorted(data_dir.glob("*.json")):
            with open(json_file, encoding="utf-8") as f:
                exercise = json.load(f)

            slug = exercise["slug"]

            row = conn.execute(
                "SELECT id FROM exercises WHERE slug = ?", (slug,)
            ).fetchone()
            if row is None:
                cursor = conn.execute(
                    "INSERT INTO exercises (slug, name) VALUES (?, ?)",
                    (slug, exercise["name"]),
                )
                exercise_id = cursor.lastrowid
            else:
                exercise_id = row["id"]

            _sync_exercise_meta(conn, exercise_id, exercise)

            # Words already stored, counted per (source, canonical) key so that a
            # sentence deliberately repeated in the JSON is not collapsed into one.
            existing: dict = {}
            for w in conn.execute(
                "SELECT id, source, canonical, theme FROM words WHERE exercise_id = ?",
                (exercise_id,),
            ):
                existing.setdefault((w["source"], w["canonical"]), []).append(dict(w))

            for word_data in exercise.get("words", []):
                key = (word_data["source"], word_data["canonical"])
                theme = word_data.get("theme", "")

                if existing.get(key):
                    # Already seeded: keep the row (and its player prefs) untouched,
                    # only realign the theme if the list was reorganised.
                    known = existing[key].pop(0)
                    if known["theme"] != theme:
                        conn.execute(
                            "UPDATE words SET theme = ? WHERE id = ?", (theme, known["id"])
                        )
                    continue

                cursor = conn.execute(
                    "INSERT INTO words (exercise_id, source, canonical, theme) "
                    "VALUES (?, ?, ?, ?)",
                    (exercise_id, word_data["source"], word_data["canonical"], theme),
                )
                word_id = cursor.lastrowid

                for form in _word_meta_forms(word_data):
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
    Return every exercise with its full metadata (level, kind, colour, prompts),
    ordered by level then by the sort_order given in its JSON file.

    ExerciseSelectionScreen builds its whole menu from this - adding a button is
    a matter of dropping a JSON file in data/, never of editing main.py.
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM exercises ORDER BY level, sort_order, name"
        ).fetchall()
    return [dict(r) for r in rows]


def get_exercise_by_slug(slug: str, db_path: Path = _DB_PATH) -> Optional[dict]:
    """Return the exercise with the given slug (all columns), or None."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM exercises WHERE slug = ?", (slug,)
        ).fetchone()
    return dict(row) if row else None


def _get_exercise(conn, exercise_id: int) -> dict:
    """Full exercise row (metadata included) as a plain dict, {} when unknown."""
    row = conn.execute("SELECT * FROM exercises WHERE id = ?", (exercise_id,)).fetchone()
    return dict(row) if row else {}


def _forms_by_word(conn, exercise_id: int) -> dict:
    """{word_id: [(label, value), ...]} for every word of an exercise, in one query."""
    result: dict = {}
    for row in conn.execute(
        """SELECT f.word_id, f.label, f.value
           FROM forms f JOIN words w ON w.id = f.word_id
           WHERE w.exercise_id = ?
           ORDER BY f.id""",
        (exercise_id,),
    ):
        result.setdefault(row["word_id"], []).append((row["label"], row["value"]))
    return result


def _fill(template: str, fallback: str, **values) -> str:
    """
    Render a prompt template from the JSON seed, e.g.
    "Traduis en allemand : « {source} »".  Falls back to `fallback` when the
    exercise defines no template, and never crashes on a stray brace.
    """
    text = template or fallback
    try:
        return text.format(**values)
    except (KeyError, IndexError, ValueError):
        return text


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

    Returns a list of dicts: {word_id, source, theme, enabled (bool)}.
    Ordered by the word's insertion order (same as the JSON seed order), which
    keeps a vocabulary list in lesson order.  `theme` is "" for exercises that
    do not group their words.
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            """SELECT w.id AS word_id, w.source, w.theme,
                      COALESCE(p.enabled, 1) AS enabled
               FROM words w
               LEFT JOIN player_word_prefs p
                      ON p.word_id = w.id AND p.player_id = ?
               WHERE w.exercise_id = ?
               ORDER BY w.rowid""",
            (player_id, exercise_id),
        ).fetchall()
    return [{"word_id": r["word_id"], "source": r["source"], "theme": r["theme"],
             "enabled": bool(r["enabled"])}
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
    Build the question pool for a "forms" exercise (Latin verbs, French moods).
    Returns a list of question dicts consumed by QuizScreen.

    enabled_word_ids: only these words are used; None means all of them.

    Each question dict has:
      type        : "canonical" | "form"
      prompt      : string shown to the student
      answer      : expected answer
      word_source : the source word (for display context)

    Question types:
      "canonical" - the canonical translation (e.g. the Latin infinitive),
                    worded by the exercise's canonical_prompt template
      "form"      - one conjugated/declined form, worded by form_prompt

    The wording comes from the JSON seed, so a German or Spanish exercise no
    longer inherits "Comment dit-on ... en latin ?".
    """
    with _connect(db_path) as conn:
        exercise = _get_exercise(conn, exercise_id)
        words = conn.execute(
            "SELECT id, source, canonical FROM words WHERE exercise_id = ? ORDER BY rowid",
            (exercise_id,),
        ).fetchall()
        forms_by_word = _forms_by_word(conn, exercise_id)

    target = exercise.get("target_language", "")
    canonical_tpl = exercise.get("prompt_canonical", "")
    form_tpl = exercise.get("prompt_form", "")

    enabled_set = set(enabled_word_ids) if enabled_word_ids is not None else None

    questions = []
    for word in words:
        word_id = word["id"]
        if enabled_set is not None and word_id not in enabled_set:
            continue

        source = word["source"]
        canonical = word["canonical"]

        if canonical:
            questions.append({
                "type": "canonical",
                "prompt": _fill(
                    canonical_tpl,
                    "Comment dit-on \u00ab\u00a0{source}\u00a0\u00bb en {target_language}\u00a0?",
                    source=source, canonical=canonical, target_language=target,
                ),
                "answer": canonical,
                "word_source": source,
            })

        for label, value in forms_by_word.get(word_id, []):
            if label.startswith("__"):
                continue   # reserved metadata row (__alt_target__, __case__...)
            questions.append({
                "type": "form",
                "prompt": _fill(
                    form_tpl,
                    "\u00ab\u00a0{source}\u00a0\u00bb \u2014 {label}",
                    source=source, canonical=canonical, label=label,
                    target_language=target,
                ),
                "answer": value,
                "word_source": source,
            })

    return questions


# ---------------------------------------------------------------------------
# Vocabulary question builder (translate both ways)
# ---------------------------------------------------------------------------

# Direction of a vocabulary question, as stored in app_state["direction"].
DIRECTION_FORWARD = "forward"   # French -> foreign language (production)
DIRECTION_REVERSE = "reverse"   # foreign language -> French (comprehension)
DIRECTION_MIXED   = "mixed"     # both, shuffled together


def get_vocab_questions(
    exercise_id: int,
    enabled_word_ids: Optional[list] = None,
    direction: str = DIRECTION_MIXED,
    db_path: Path = _DB_PATH,
) -> list:
    """
    Build the question pool for a "vocab" exercise (German vocabulary list).

    One word yields up to two questions - "le père" -> "der Vater" and
    "der Vater" -> "le père" - and `direction` selects which ones are kept.

    Each question dict has, on top of the QuizScreen basics:
      accepted    : every answer that counts as correct (expected + synonyms
                    declared as alt_source / alt_target in the JSON)
      answer_lang : "de" / "fr" - which tolerance answers.matches() applies
      theme       : the vocabulary chapter, kept for future per-theme stats
    """
    with _connect(db_path) as conn:
        exercise = _get_exercise(conn, exercise_id)
        words = conn.execute(
            "SELECT id, source, canonical, theme FROM words "
            "WHERE exercise_id = ? ORDER BY rowid",
            (exercise_id,),
        ).fetchall()
        forms_by_word = _forms_by_word(conn, exercise_id)

    source_language = exercise.get("source_language", "français")
    target_language = exercise.get("target_language", "")
    source_code = exercise.get("source_lang_code", "")
    target_code = exercise.get("target_lang_code", "")
    forward_tpl = exercise.get("prompt_canonical", "")
    reverse_tpl = exercise.get("prompt_reverse", "")

    enabled_set = set(enabled_word_ids) if enabled_word_ids is not None else None

    questions = []
    for word in words:
        word_id = word["id"]
        if enabled_set is not None and word_id not in enabled_set:
            continue

        source = word["source"]
        canonical = word["canonical"]
        if not canonical:
            continue

        metadata = forms_by_word.get(word_id, [])
        alt_target = [v for label, v in metadata if label == "__alt_target__"]
        alt_source = [v for label, v in metadata if label == "__alt_source__"]

        prompt_args = dict(
            source=source, canonical=canonical,
            source_language=source_language, target_language=target_language,
        )

        if direction in (DIRECTION_FORWARD, DIRECTION_MIXED):
            questions.append({
                "type": "vocab",
                "direction": DIRECTION_FORWARD,
                "prompt": _fill(
                    forward_tpl,
                    "Traduis en {target_language}\u00a0: \u00ab\u00a0{source}\u00a0\u00bb",
                    **prompt_args,
                ),
                "answer": canonical,
                "accepted": [canonical] + alt_target,
                "answer_lang": target_code,
                "word_source": source,
                "theme": word["theme"],
            })

        if direction in (DIRECTION_REVERSE, DIRECTION_MIXED):
            questions.append({
                "type": "vocab",
                "direction": DIRECTION_REVERSE,
                "prompt": _fill(
                    reverse_tpl,
                    "Traduis en {source_language}\u00a0: \u00ab\u00a0{canonical}\u00a0\u00bb",
                    **prompt_args,
                ),
                "answer": source,
                "accepted": [source] + alt_source,
                "answer_lang": source_code,
                "word_source": source,
                "theme": word["theme"],
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
        forms_by_word = _forms_by_word(conn, exercise_id)

    enabled_set = set(enabled_word_ids) if enabled_word_ids is not None else None

    questions = []
    for word in words:
        word_id = word["id"]
        if enabled_set is not None and word_id not in enabled_set:
            continue

        forms_dict = dict(forms_by_word.get(word_id, []))
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
        forms_by_word = _forms_by_word(conn, exercise_id)

    questions = []
    for word in words:
        word_id = word["id"]
        meta = dict(forms_by_word.get(word_id, []))
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
