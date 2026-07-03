import sqlite3
from contextlib import contextmanager

from config import DB_PATH


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        c = conn.cursor()

        c.execute("""
            CREATE TABLE IF NOT EXISTS students (
                student_id TEXT PRIMARY KEY,
                telegram_id INTEGER UNIQUE,
                name TEXT,
                status TEXT DEFAULT 'active',
                assigned_tutor_id TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS parents (
                parent_id TEXT PRIMARY KEY,
                telegram_id INTEGER UNIQUE,
                name TEXT,
                child_student_id TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS tutors (
                tutor_id TEXT PRIMARY KEY,
                telegram_id INTEGER UNIQUE,
                name TEXT,
                subject TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                subject TEXT NOT NULL,
                score INTEGER NOT NULL,
                tutor_id TEXT,
                recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(student_id)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                tutor_id TEXT,
                topic TEXT,
                session_date TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(student_id)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_id TEXT NOT NULL,
                student_id TEXT,
                amount TEXT,
                receipt_file_id TEXT,
                status TEXT DEFAULT 'pending',
                submitted_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (parent_id) REFERENCES parents(parent_id)
            )
        """)

    print("✅ Database ready")


# ---------------------------------------------------------------------
# Lookup / linking
# ---------------------------------------------------------------------

def link_student(student_id: str, telegram_id: int):
    """Return the student row if student_id exists, linking telegram_id
    on first login. Returns None if the ID isn't registered."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM students WHERE student_id = ?", (student_id,)
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE students SET telegram_id = ? WHERE student_id = ? AND telegram_id IS NULL",
            (telegram_id, student_id),
        )
        return row


def link_parent(parent_id: str, telegram_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM parents WHERE parent_id = ?", (parent_id,)
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE parents SET telegram_id = ? WHERE parent_id = ? AND telegram_id IS NULL",
            (telegram_id, parent_id),
        )
        return row


def link_tutor(tutor_id: str, telegram_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM tutors WHERE tutor_id = ?", (tutor_id,)
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE tutors SET telegram_id = ? WHERE tutor_id = ? AND telegram_id IS NULL",
            (telegram_id, tutor_id),
        )
        return row


# ---------------------------------------------------------------------
# Admin: registration
# ---------------------------------------------------------------------

def register_student(student_id, name, assigned_tutor_id=None):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO students (student_id, name, status, assigned_tutor_id, telegram_id) "
            "VALUES (?, ?, COALESCE((SELECT status FROM students WHERE student_id = ?), 'active'), ?, "
            "(SELECT telegram_id FROM students WHERE student_id = ?))",
            (student_id, name, student_id, assigned_tutor_id, student_id),
        )


def register_parent(parent_id, name, child_student_id):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO parents (parent_id, name, child_student_id, telegram_id) "
            "VALUES (?, ?, ?, (SELECT telegram_id FROM parents WHERE parent_id = ?))",
            (parent_id, name, child_student_id, parent_id),
        )


def register_tutor(tutor_id, name, subject):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO tutors (tutor_id, name, subject, telegram_id) "
            "VALUES (?, ?, ?, (SELECT telegram_id FROM tutors WHERE tutor_id = ?))",
            (tutor_id, name, subject, tutor_id),
        )


def set_student_status(student_id, status):
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE students SET status = ? WHERE student_id = ?", (status, student_id)
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------------
# Results & sessions
# ---------------------------------------------------------------------

def add_result(student_id, subject, score, tutor_id):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO results (student_id, subject, score, tutor_id) VALUES (?, ?, ?, ?)",
            (student_id, subject, score, tutor_id),
        )


def get_results(student_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT subject, score, recorded_at FROM results "
            "WHERE student_id = ? ORDER BY recorded_at DESC",
            (student_id,),
        ).fetchall()


def add_session(student_id, tutor_id, topic, session_date):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sessions (student_id, tutor_id, topic, session_date) VALUES (?, ?, ?, ?)",
            (student_id, tutor_id, topic, session_date),
        )


def get_next_session(student_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT topic, session_date FROM sessions "
            "WHERE student_id = ? ORDER BY session_date ASC LIMIT 1",
            (student_id,),
        ).fetchone()


def get_students_for_tutor(tutor_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT student_id, name, status FROM students WHERE assigned_tutor_id = ?",
            (tutor_id,),
        ).fetchall()


def get_tutor_for_student(student_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT t.tutor_id, t.name, t.subject FROM tutors t "
            "JOIN students s ON s.assigned_tutor_id = t.tutor_id "
            "WHERE s.student_id = ?",
            (student_id,),
        ).fetchone()


def get_student(student_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM students WHERE student_id = ?", (student_id,)
        ).fetchone()


# ---------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------

def submit_payment(parent_id, student_id, amount, receipt_file_id):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO payments (parent_id, student_id, amount, receipt_file_id) "
            "VALUES (?, ?, ?, ?)",
            (parent_id, student_id, amount, receipt_file_id),
        )
        return cur.lastrowid


def get_pending_payments():
    with get_conn() as conn:
        return conn.execute(
            "SELECT id, parent_id, student_id, amount, receipt_file_id, submitted_at "
            "FROM payments WHERE status = 'pending' ORDER BY submitted_at ASC"
        ).fetchall()


def set_payment_status(payment_id, status):
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE payments SET status = ? WHERE id = ?", (status, payment_id)
        )
        return cur.rowcount > 0


def get_payment(payment_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM payments WHERE id = ?", (payment_id,)
        ).fetchone()