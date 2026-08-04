"""Populate the database with sample data for local testing.

    python seed.py            # add sample rows (safe to re-run)
    python seed.py --reset    # delete the database file first

Requires DB_PATH from .env (or the default wave_academy.db). Does NOT need a
bot token, so you can seed before setting one up.
"""

import argparse
import os
import sys
from datetime import date, timedelta

import db
from config import ADMIN_TELEGRAM_IDS, DB_PATH

STUDENTS = [
    ("STU001", "Abel Tesfaye"),
    ("STU002", "Hana Girma"),
    ("STU003", "Yonas Bekele"),
]
TUTORS = [
    ("TUT001", "Meron Alemu", "Mathematics"),
    ("TUT002", "Samuel Kebede", "Physics"),
]
PARENTS = [
    ("PAR001", "Tigist Haile", ["STU001", "STU002"]),  # two children
    ("PAR002", "Getachew Assefa", ["STU003"]),
]
ASSIGNMENTS = [
    ("TUT001", "STU001", "Mathematics"),
    ("TUT001", "STU002", "Mathematics"),
    ("TUT002", "STU003", "Physics"),
]
RESULTS = [
    ("STU001", "Mathematics", 88, 100, "TUT001"),
    ("STU001", "Mathematics", 74, 100, "TUT001"),
    ("STU002", "Mathematics", 61, 100, "TUT001"),
    ("STU003", "Physics", 95, 120, "TUT002"),
]


def seed():
    db.init_db()

    for tutor_id, name, subject in TUTORS:
        db.register_tutor(tutor_id, name, subject)
        db.approve_tutor(tutor_id)  # pre-approved so you can log in immediately

    for student_id, name in STUDENTS:
        db.register_student(student_id, name)

    for parent_id, name, children in PARENTS:
        db.register_parent(parent_id, name)
        for child in children:
            db.link_parent_child(parent_id, child)

    for tutor_id, student_id, subject in ASSIGNMENTS:
        db.assign_tutor(tutor_id, student_id, subject)

    for student_id, subject, score, max_score, tutor_id in RESULTS:
        db.add_result(student_id, subject, score, max_score, tutor_id)

    upcoming = (date.today() + timedelta(days=3)).isoformat()
    db.add_session("STU001", "TUT001", "Quadratic equations", upcoming)
    db.add_session("STU002", "TUT001", "Trigonometry basics", upcoming)
    db.add_session("STU003", "TUT002", "Newton's laws", upcoming)

    db.set_student_status("STU003", "suspended")

    if ADMIN_TELEGRAM_IDS:
        db.seed_admins(ADMIN_TELEGRAM_IDS)

    print(f"✅ Seeded {DB_PATH}\n")
    print("  Students:", ", ".join(s for s, _ in STUDENTS))
    print("  Tutors:  ", ", ".join(t for t, _, _ in TUTORS), "(approved)")
    print("  Parents: ", ", ".join(p for p, _, _ in PARENTS))
    if ADMIN_TELEGRAM_IDS:
        print("  Admins:  ", ", ".join(str(a) for a in ADMIN_TELEGRAM_IDS))
    else:
        print("\n⚠️  ADMIN_TELEGRAM_IDS is empty in .env — set it before running bot.py,")
        print("   otherwise nobody can approve tutors or payments.")
    print("\nLog in with /start and one of the IDs above.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true",
                        help="delete the database file before seeding")
    args = parser.parse_args()

    if args.reset and os.path.exists(DB_PATH):
        confirm = input(f"Delete {DB_PATH} and all its data? [y/N] ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            sys.exit(1)
        os.remove(DB_PATH)
        print(f"Removed {DB_PATH}")

    seed()


if __name__ == "__main__":
    main()
