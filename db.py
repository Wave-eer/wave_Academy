"""SQLite schema and data access for Wave Academy.

All access goes through get_conn(), which enables foreign keys and commits on
clean exit. Callers get sqlite3.Row objects (dict-like access by column name).

Schema overview
---------------
    students        one row per learner; status drives "My Status"
    parents         one row per guardian
    parent_students many-to-many: a parent may have several children
    tutors          one row per tutor; `approved` gates login until an admin says yes
    tutor_students  many-to-many: which tutor teaches which student, per subject
    admins          Telegram IDs with admin rights (seeded from ADMIN_TELEGRAM_IDS)
    results         one grade entry (student, subject, score, who recorded it)
    sessions        a scheduled study session with topic and date
    payments        a submitted receipt awaiting admin approval

Relationships are enforced with real FOREIGN KEY constraints, so a grade
cannot reference a student who does not exist.
"""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime

from config import DB_PATH

logger = logging.getLogger(__name__)

VALID_STUDENT_STATUSES = ("active", "inactive", "suspended", "graduated")
VALID_PAYMENT_STATUSES = ("pending", "approved", "rejected")


class DatabaseError(Exception):
    """Raised when a database operation fails in a way the caller should report."""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        logger.exception("Database operation failed")
        raise DatabaseError(str(exc)) from exc
    finally:
        conn.close()


# ---------------------------------------------------------------------
# Schema creation and migration
# ---------------------------------------------------------------------

def _columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def _table_exists(conn, table):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def init_db():
    """Create any missing tables/columns. Safe to run on an existing database."""
    with get_conn() as conn:
        c = conn.cursor()

        c.execute("""
            CREATE TABLE IF NOT EXISTS students (
                student_id        TEXT PRIMARY KEY,
                telegram_id       INTEGER UNIQUE,
                name              TEXT NOT NULL,
                status            TEXT NOT NULL DEFAULT 'active',
                assigned_tutor_id TEXT,
                created_at        TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS parents (
                parent_id        TEXT PRIMARY KEY,
                telegram_id      INTEGER UNIQUE,
                name             TEXT NOT NULL,
                child_student_id TEXT,
                created_at       TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS tutors (
                tutor_id    TEXT PRIMARY KEY,
                telegram_id INTEGER UNIQUE,
                name        TEXT NOT NULL,
                subject     TEXT,
                phone       TEXT,
                approved    INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                telegram_id INTEGER PRIMARY KEY,
                name        TEXT,
                added_at    TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # A parent can have more than one child enrolled.
        c.execute("""
            CREATE TABLE IF NOT EXISTS parent_students (
                parent_id  TEXT NOT NULL,
                student_id TEXT NOT NULL,
                PRIMARY KEY (parent_id, student_id),
                FOREIGN KEY (parent_id)  REFERENCES parents(parent_id)   ON DELETE CASCADE,
                FOREIGN KEY (student_id) REFERENCES students(student_id) ON DELETE CASCADE
            )
        """)

        # A student may have different tutors for different subjects.
        c.execute("""
            CREATE TABLE IF NOT EXISTS tutor_students (
                tutor_id   TEXT NOT NULL,
                student_id TEXT NOT NULL,
                subject    TEXT,
                PRIMARY KEY (tutor_id, student_id),
                FOREIGN KEY (tutor_id)   REFERENCES tutors(tutor_id)     ON DELETE CASCADE,
                FOREIGN KEY (student_id) REFERENCES students(student_id) ON DELETE CASCADE
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS results (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id  TEXT NOT NULL,
                subject     TEXT NOT NULL,
                score       INTEGER NOT NULL,
                max_score   INTEGER NOT NULL DEFAULT 100,
                tutor_id    TEXT,
                recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(student_id) ON DELETE CASCADE,
                FOREIGN KEY (tutor_id)   REFERENCES tutors(tutor_id)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id   TEXT NOT NULL,
                tutor_id     TEXT,
                topic        TEXT NOT NULL,
                session_date TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT 'scheduled',
                created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(student_id) ON DELETE CASCADE,
                FOREIGN KEY (tutor_id)   REFERENCES tutors(tutor_id)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                submitter_role   TEXT NOT NULL,
                submitter_id     TEXT NOT NULL,
                student_id       TEXT,
                amount           REAL,
                currency         TEXT DEFAULT 'ETB',
                note             TEXT,
                receipt_file_id  TEXT NOT NULL,
                receipt_kind     TEXT NOT NULL DEFAULT 'photo',
                status           TEXT NOT NULL DEFAULT 'pending',
                submitted_at     TEXT DEFAULT CURRENT_TIMESTAMP,
                reviewed_by      INTEGER,
                reviewed_at      TEXT,
                FOREIGN KEY (student_id) REFERENCES students(student_id)
            )
        """)

        for stmt in (
            "CREATE INDEX IF NOT EXISTS idx_results_student ON results(student_id)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_student ON sessions(student_id, session_date)",
            "CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)",
            "CREATE INDEX IF NOT EXISTS idx_ts_tutor ON tutor_students(tutor_id)",
            "CREATE INDEX IF NOT EXISTS idx_ps_parent ON parent_students(parent_id)",
        ):
            c.execute(stmt)

        _migrate(conn)

    logger.info("Database ready at %s", DB_PATH)


def _migrate(conn):
    """Bring an older database up to the current shape, without losing data."""
    c = conn.cursor()

    # Columns added after the first release.
    added = {
        "students": [("telegram_id", "INTEGER"), ("assigned_tutor_id", "TEXT"),
                     ("created_at", "TEXT")],
        "parents": [("telegram_id", "INTEGER"), ("child_student_id", "TEXT"),
                    ("created_at", "TEXT")],
        "tutors": [("telegram_id", "INTEGER"), ("subject", "TEXT"), ("phone", "TEXT"),
                   ("approved", "INTEGER NOT NULL DEFAULT 0"), ("created_at", "TEXT")],
        "results": [("max_score", "INTEGER NOT NULL DEFAULT 100"), ("tutor_id", "TEXT"),
                    ("recorded_at", "TEXT")],
        "sessions": [("status", "TEXT NOT NULL DEFAULT 'scheduled'")],
    }
    for table, cols in added.items():
        if not _table_exists(conn, table):
            continue
        existing = _columns(conn, table)
        for name, decl in cols:
            if name not in existing:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
                logger.info("Migrated: added %s.%s", table, name)

    # The original payments table used parent_id/TEXT amount. Rebuild it if so.
    if _table_exists(conn, "payments"):
        pay_cols = _columns(conn, "payments")
        if "submitter_role" not in pay_cols:
            logger.info("Migrating payments table to the new layout")
            c.execute("ALTER TABLE payments RENAME TO payments_old")
            c.execute("""
                CREATE TABLE payments (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    submitter_role   TEXT NOT NULL,
                    submitter_id     TEXT NOT NULL,
                    student_id       TEXT,
                    amount           REAL,
                    currency         TEXT DEFAULT 'ETB',
                    note             TEXT,
                    receipt_file_id  TEXT NOT NULL,
                    receipt_kind     TEXT NOT NULL DEFAULT 'photo',
                    status           TEXT NOT NULL DEFAULT 'pending',
                    submitted_at     TEXT DEFAULT CURRENT_TIMESTAMP,
                    reviewed_by      INTEGER,
                    reviewed_at      TEXT,
                    FOREIGN KEY (student_id) REFERENCES students(student_id)
                )
            """)
            old = _columns(conn, "payments_old")
            if {"parent_id", "receipt_file_id"} <= old:
                c.execute("""
                    INSERT INTO payments
                        (id, submitter_role, submitter_id, student_id, amount,
                         receipt_file_id, receipt_kind, status, submitted_at)
                    SELECT id, 'parent', parent_id, student_id,
                           CAST(REPLACE(COALESCE(amount,'0'), ',', '') AS REAL),
                           receipt_file_id, 'photo',
                           COALESCE(status,'pending'), submitted_at
                    FROM payments_old
                """)
            c.execute("DROP TABLE payments_old")

    # Fold the old one-child-per-parent column into the junction table.
    if _table_exists(conn, "parents") and "child_student_id" in _columns(conn, "parents"):
        c.execute("""
            INSERT OR IGNORE INTO parent_students (parent_id, student_id)
            SELECT parent_id, child_student_id FROM parents
            WHERE child_student_id IS NOT NULL AND child_student_id <> ''
              AND child_student_id IN (SELECT student_id FROM students)
        """)

    # Same for the single assigned tutor.
    if _table_exists(conn, "students") and "assigned_tutor_id" in _columns(conn, "students"):
        c.execute("""
            INSERT OR IGNORE INTO tutor_students (tutor_id, student_id, subject)
            SELECT s.assigned_tutor_id, s.student_id, t.subject
            FROM students s JOIN tutors t ON t.tutor_id = s.assigned_tutor_id
            WHERE s.assigned_tutor_id IS NOT NULL AND s.assigned_tutor_id <> ''
        """)


def seed_admins(telegram_ids):
    """Ensure bootstrap admins from .env exist in the admins table."""
    with get_conn() as conn:
        for tid in telegram_ids:
            conn.execute(
                "INSERT OR IGNORE INTO admins (telegram_id, name) VALUES (?, ?)",
                (tid, "bootstrap admin"),
            )


# ---------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------

def parse_score(text):
    """Return (score, error). Accepts '85' or '85/120'."""
    text = (text or "").strip()
    max_score = 100
    if "/" in text:
        left, _, right = text.partition("/")
        text, right = left.strip(), right.strip()
        if not right.isdigit() or int(right) <= 0:
            return None, "The maximum score must be a positive whole number, e.g. 85/120."
        max_score = int(right)
    if not text.isdigit():
        return None, "Enter the score as a whole number, e.g. 85 or 85/120."
    score = int(text)
    if score > max_score:
        return None, f"The score cannot be higher than the maximum ({max_score})."
    return (score, max_score), None


def parse_amount(text):
    """Return (amount, error). Accepts '500', '500.50', '1,200'."""
    cleaned = (text or "").strip().replace(",", "").replace(" ", "")
    for prefix in ("ETB", "etb", "birr", "Birr", "$"):
        cleaned = cleaned.replace(prefix, "")
    try:
        amount = float(cleaned)
    except ValueError:
        return None, "Enter the amount as a number, e.g. 500 or 1200.50."
    if amount <= 0:
        return None, "The amount must be greater than zero."
    if amount > 1_000_000:
        return None, "That amount looks too large. Please check and re-enter."
    return round(amount, 2), None


def parse_date(text):
    """Return (iso_date, error). Requires YYYY-MM-DD and refuses past dates."""
    text = (text or "").strip()
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None, "Use the format YYYY-MM-DD, for example 2026-09-15."
    if parsed < date.today():
        return None, "That date is in the past. Enter today or a future date."
    if (parsed - date.today()).days > 730:
        return None, "That date is more than two years away. Please check it."
    return parsed.isoformat(), None


# ---------------------------------------------------------------------
# Identity: who is this Telegram user?
# ---------------------------------------------------------------------

def is_admin(telegram_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT 1 FROM admins WHERE telegram_id = ?", (telegram_id,)
        ).fetchone() is not None


def add_admin(telegram_id, name=None):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO admins (telegram_id, name) VALUES (?, ?)",
            (telegram_id, name),
        )


def remove_admin(telegram_id):
    with get_conn() as conn:
        return conn.execute(
            "DELETE FROM admins WHERE telegram_id = ?", (telegram_id,)
        ).rowcount > 0


def list_admins():
    with get_conn() as conn:
        return conn.execute(
            "SELECT telegram_id, name, added_at FROM admins ORDER BY added_at"
        ).fetchall()


def _link(conn, table, id_col, record_id, telegram_id):
    """Attach a Telegram account to a record, refusing to steal another's login."""
    row = conn.execute(
        f"SELECT * FROM {table} WHERE {id_col} = ?", (record_id,)
    ).fetchone()
    if row is None:
        return None, "not_found"
    if row["telegram_id"] is not None and row["telegram_id"] != telegram_id:
        return None, "claimed"
    if row["telegram_id"] is None:
        taken = conn.execute(
            f"SELECT {id_col} FROM {table} WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if taken:
            return None, "other_account"
        conn.execute(
            f"UPDATE {table} SET telegram_id = ? WHERE {id_col} = ?",
            (telegram_id, record_id),
        )
        row = conn.execute(
            f"SELECT * FROM {table} WHERE {id_col} = ?", (record_id,)
        ).fetchone()
    return row, None


def link_student(student_id, telegram_id):
    with get_conn() as conn:
        return _link(conn, "students", "student_id", student_id, telegram_id)


def link_parent(parent_id, telegram_id):
    with get_conn() as conn:
        return _link(conn, "parents", "parent_id", parent_id, telegram_id)


def link_tutor(tutor_id, telegram_id):
    with get_conn() as conn:
        row, err = _link(conn, "tutors", "tutor_id", tutor_id, telegram_id)
        if row is not None and not row["approved"]:
            return None, "unapproved"
        return row, err


# ---------------------------------------------------------------------
# Registration (admin)
# ---------------------------------------------------------------------

def register_student(student_id, name, tutor_id=None):
    with get_conn() as conn:
        exists = conn.execute(
            "SELECT 1 FROM students WHERE student_id = ?", (student_id,)
        ).fetchone()
        if exists:
            conn.execute(
                "UPDATE students SET name = ? WHERE student_id = ?", (name, student_id)
            )
        else:
            conn.execute(
                "INSERT INTO students (student_id, name) VALUES (?, ?)",
                (student_id, name),
            )
        if tutor_id:
            if not conn.execute(
                "SELECT 1 FROM tutors WHERE tutor_id = ?", (tutor_id,)
            ).fetchone():
                return False, f"Tutor {tutor_id} does not exist."
            conn.execute(
                "UPDATE students SET assigned_tutor_id = ? WHERE student_id = ?",
                (tutor_id, student_id),
            )
            conn.execute(
                "INSERT OR IGNORE INTO tutor_students (tutor_id, student_id) VALUES (?, ?)",
                (tutor_id, student_id),
            )
        return True, None


def register_parent(parent_id, name, child_student_id=None):
    with get_conn() as conn:
        if child_student_id and not conn.execute(
            "SELECT 1 FROM students WHERE student_id = ?", (child_student_id,)
        ).fetchone():
            return False, f"Student {child_student_id} does not exist. Register them first."
        exists = conn.execute(
            "SELECT 1 FROM parents WHERE parent_id = ?", (parent_id,)
        ).fetchone()
        if exists:
            conn.execute("UPDATE parents SET name = ? WHERE parent_id = ?", (name, parent_id))
        else:
            conn.execute(
                "INSERT INTO parents (parent_id, name) VALUES (?, ?)", (parent_id, name)
            )
        if child_student_id:
            conn.execute(
                "UPDATE parents SET child_student_id = ? WHERE parent_id = ?",
                (child_student_id, parent_id),
            )
            conn.execute(
                "INSERT OR IGNORE INTO parent_students (parent_id, student_id) VALUES (?, ?)",
                (parent_id, child_student_id),
            )
        return True, None


def register_tutor(tutor_id, name, subject=None, approved=False):
    with get_conn() as conn:
        exists = conn.execute(
            "SELECT 1 FROM tutors WHERE tutor_id = ?", (tutor_id,)
        ).fetchone()
        if exists:
            conn.execute(
                "UPDATE tutors SET name = ?, subject = ? WHERE tutor_id = ?",
                (name, subject, tutor_id),
            )
        else:
            conn.execute(
                "INSERT INTO tutors (tutor_id, name, subject, approved) VALUES (?, ?, ?, ?)",
                (tutor_id, name, subject, 1 if approved else 0),
            )
        return True, None


def approve_tutor(tutor_id):
    with get_conn() as conn:
        return conn.execute(
            "UPDATE tutors SET approved = 1 WHERE tutor_id = ?", (tutor_id,)
        ).rowcount > 0


def revoke_tutor(tutor_id):
    with get_conn() as conn:
        return conn.execute(
            "UPDATE tutors SET approved = 0 WHERE tutor_id = ?", (tutor_id,)
        ).rowcount > 0


def list_pending_tutors():
    with get_conn() as conn:
        return conn.execute(
            "SELECT tutor_id, name, subject, created_at FROM tutors "
            "WHERE approved = 0 ORDER BY created_at"
        ).fetchall()


def assign_tutor(tutor_id, student_id, subject=None):
    with get_conn() as conn:
        if not conn.execute("SELECT 1 FROM tutors WHERE tutor_id = ?", (tutor_id,)).fetchone():
            return False, f"Tutor {tutor_id} does not exist."
        if not conn.execute(
            "SELECT 1 FROM students WHERE student_id = ?", (student_id,)
        ).fetchone():
            return False, f"Student {student_id} does not exist."
        conn.execute(
            "INSERT OR REPLACE INTO tutor_students (tutor_id, student_id, subject) "
            "VALUES (?, ?, ?)",
            (tutor_id, student_id, subject),
        )
        conn.execute(
            "UPDATE students SET assigned_tutor_id = COALESCE(assigned_tutor_id, ?) "
            "WHERE student_id = ?",
            (tutor_id, student_id),
        )
        return True, None


def link_parent_child(parent_id, student_id):
    with get_conn() as conn:
        if not conn.execute(
            "SELECT 1 FROM parents WHERE parent_id = ?", (parent_id,)
        ).fetchone():
            return False, f"Parent {parent_id} does not exist."
        if not conn.execute(
            "SELECT 1 FROM students WHERE student_id = ?", (student_id,)
        ).fetchone():
            return False, f"Student {student_id} does not exist."
        conn.execute(
            "INSERT OR IGNORE INTO parent_students (parent_id, student_id) VALUES (?, ?)",
            (parent_id, student_id),
        )
        return True, None


def set_student_status(student_id, status):
    if status not in VALID_STUDENT_STATUSES:
        return False, f"Status must be one of: {', '.join(VALID_STUDENT_STATUSES)}."
    with get_conn() as conn:
        ok = conn.execute(
            "UPDATE students SET status = ? WHERE student_id = ?", (status, student_id)
        ).rowcount > 0
        return ok, None if ok else f"Student {student_id} not found."


# ---------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------

def get_student(student_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM students WHERE student_id = ?", (student_id,)
        ).fetchone()


def get_tutor(tutor_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM tutors WHERE tutor_id = ?", (tutor_id,)
        ).fetchone()


def list_students(limit=50):
    with get_conn() as conn:
        return conn.execute(
            "SELECT student_id, name, status, telegram_id FROM students "
            "ORDER BY student_id LIMIT ?",
            (limit,),
        ).fetchall()


def list_tutors(limit=50):
    with get_conn() as conn:
        return conn.execute(
            "SELECT tutor_id, name, subject, approved FROM tutors "
            "ORDER BY tutor_id LIMIT ?",
            (limit,),
        ).fetchall()


def list_parents(limit=50):
    with get_conn() as conn:
        return conn.execute(
            "SELECT parent_id, name, telegram_id FROM parents ORDER BY parent_id LIMIT ?",
            (limit,),
        ).fetchall()


def get_children(parent_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT s.student_id, s.name, s.status FROM students s "
            "JOIN parent_students ps ON ps.student_id = s.student_id "
            "WHERE ps.parent_id = ? ORDER BY s.name",
            (parent_id,),
        ).fetchall()


def get_parents_for_student(student_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT p.parent_id, p.name, p.telegram_id FROM parents p "
            "JOIN parent_students ps ON ps.parent_id = p.parent_id "
            "WHERE ps.student_id = ?",
            (student_id,),
        ).fetchall()


def get_students_for_tutor(tutor_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT s.student_id, s.name, s.status, ts.subject FROM students s "
            "JOIN tutor_students ts ON ts.student_id = s.student_id "
            "WHERE ts.tutor_id = ? ORDER BY s.name",
            (tutor_id,),
        ).fetchall()


def tutor_teaches(tutor_id, student_id):
    """Authorization check: may this tutor write data for this student?"""
    with get_conn() as conn:
        return conn.execute(
            "SELECT 1 FROM tutor_students WHERE tutor_id = ? AND student_id = ?",
            (tutor_id, student_id),
        ).fetchone() is not None


def get_tutors_for_student(student_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT t.tutor_id, t.name, t.subject, t.phone, t.telegram_id "
            "FROM tutors t JOIN tutor_students ts ON ts.tutor_id = t.tutor_id "
            "WHERE ts.student_id = ?",
            (student_id,),
        ).fetchall()


# ---------------------------------------------------------------------
# Results and sessions
# ---------------------------------------------------------------------

def add_result(student_id, subject, score, max_score, tutor_id):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO results (student_id, subject, score, max_score, tutor_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (student_id, subject, score, max_score, tutor_id),
        )
        return cur.lastrowid


def get_results(student_id, limit=20):
    with get_conn() as conn:
        return conn.execute(
            "SELECT subject, score, max_score, recorded_at, tutor_id FROM results "
            "WHERE student_id = ? ORDER BY recorded_at DESC LIMIT ?",
            (student_id, limit),
        ).fetchall()


def get_performance(student_id):
    """Average percentage overall and per subject — powers 'Performance Status'."""
    with get_conn() as conn:
        overall = conn.execute(
            "SELECT COUNT(*) AS n, "
            "       AVG(CAST(score AS REAL) * 100 / max_score) AS pct "
            "FROM results WHERE student_id = ? AND max_score > 0",
            (student_id,),
        ).fetchone()
        per_subject = conn.execute(
            "SELECT subject, COUNT(*) AS n, "
            "       AVG(CAST(score AS REAL) * 100 / max_score) AS pct "
            "FROM results WHERE student_id = ? AND max_score > 0 "
            "GROUP BY subject ORDER BY subject",
            (student_id,),
        ).fetchall()
        return overall, per_subject


def add_session(student_id, tutor_id, topic, session_date):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO sessions (student_id, tutor_id, topic, session_date) "
            "VALUES (?, ?, ?, ?)",
            (student_id, tutor_id, topic, session_date),
        )
        return cur.lastrowid


def get_next_session(student_id):
    """The soonest session that has not already passed."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT s.topic, s.session_date, t.name AS tutor_name "
            "FROM sessions s LEFT JOIN tutors t ON t.tutor_id = s.tutor_id "
            "WHERE s.student_id = ? AND s.status = 'scheduled' AND s.session_date >= ? "
            "ORDER BY s.session_date ASC LIMIT 1",
            (student_id, date.today().isoformat()),
        ).fetchone()


# ---------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------

def submit_payment(submitter_role, submitter_id, student_id, amount, currency,
                   receipt_file_id, receipt_kind, note=None):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO payments (submitter_role, submitter_id, student_id, amount, "
            "currency, note, receipt_file_id, receipt_kind) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (submitter_role, submitter_id, student_id, amount, currency, note,
             receipt_file_id, receipt_kind),
        )
        return cur.lastrowid


def get_payment(payment_id):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()


def get_pending_payments(limit=30):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM payments WHERE status = 'pending' "
            "ORDER BY submitted_at ASC LIMIT ?",
            (limit,),
        ).fetchall()


def get_all_payments(limit=30):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM payments ORDER BY submitted_at DESC LIMIT ?", (limit,)
        ).fetchall()


def get_payments_for_submitter(role, submitter_id, limit=10):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM payments WHERE submitter_role = ? AND submitter_id = ? "
            "ORDER BY submitted_at DESC LIMIT ?",
            (role, submitter_id, limit),
        ).fetchall()


def set_payment_status(payment_id, status, reviewed_by):
    """Only a pending payment can be decided, so two admins cannot both approve."""
    if status not in VALID_PAYMENT_STATUSES:
        return False, f"Status must be one of: {', '.join(VALID_PAYMENT_STATUSES)}."
    with get_conn() as conn:
        row = conn.execute("SELECT status FROM payments WHERE id = ?", (payment_id,)).fetchone()
        if row is None:
            return False, f"Payment #{payment_id} not found."
        if row["status"] != "pending":
            return False, f"Payment #{payment_id} was already {row['status']}."
        conn.execute(
            "UPDATE payments SET status = ?, reviewed_by = ?, reviewed_at = ? WHERE id = ?",
            (status, reviewed_by, datetime.now().isoformat(timespec="seconds"), payment_id),
        )
        return True, None


def get_submitter_telegram_id(role, submitter_id):
    """Used to tell a parent/student their receipt was approved or rejected."""
    table, col = ("parents", "parent_id") if role == "parent" else ("students", "student_id")
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT telegram_id FROM {table} WHERE {col} = ?", (submitter_id,)
        ).fetchone()
        return row["telegram_id"] if row else None
