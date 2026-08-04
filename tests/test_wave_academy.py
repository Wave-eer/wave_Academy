"""Offline test suite for Wave Academy.

Runs against a throwaway SQLite database with fake Telegram objects, so it
needs no bot token and no network access:

    python tests/test_wave_academy.py

Exits non-zero on the first failure.
"""

import asyncio
import os
import sys
import tempfile
from datetime import date, timedelta

# Point config at a temporary database *before* importing it, and make the
# project importable when this file is run directly from anywhere.
_TMP = tempfile.mkdtemp(prefix="wave-academy-test-")
os.environ["DB_PATH"] = os.path.join(_TMP, "test.db")
os.environ["ADMIN_TELEGRAM_IDS"] = "111"
os.environ["BOT_TOKEN"] = "123456:test-token-not-used-offline"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bot  # noqa: E402
import db  # noqa: E402
from telegram.ext import ConversationHandler  # noqa: E402

FUTURE = (date.today() + timedelta(days=5)).isoformat()


# ---------------------------------------------------------------------
# Fake Telegram objects — just enough surface for the handlers
# ---------------------------------------------------------------------

SENT = []  # every outgoing message, so tests can assert on notifications


class FakeMessage:
    def __init__(self, text=None, photo=None, document=None, caption=None):
        self.text = text
        self.photo = photo
        self.document = document
        self.caption = caption

    async def reply_text(self, text, **kwargs):
        SENT.append(("reply", text))
        return self


class FakeCallbackQuery:
    def __init__(self, data, message):
        self.data = data
        self.message = message

    async def answer(self, *args, **kwargs):
        pass

    async def edit_message_text(self, text, **kwargs):
        SENT.append(("edit", text))

    async def edit_message_caption(self, caption=None, **kwargs):
        SENT.append(("caption", caption))


class FakeUpdate:
    def __init__(self, user_id, text=None, data=None, photo=None, document=None):
        self.effective_user = type("U", (), {"id": user_id, "first_name": "Tester"})()
        self.effective_chat = type("C", (), {"id": user_id})()
        message = FakeMessage(text, photo, document)
        self.message = None if data else message
        self.callback_query = FakeCallbackQuery(data, message) if data else None
        self.effective_message = message


class FakeBot:
    async def send_message(self, chat_id, text=None, **kwargs):
        SENT.append(("dm", chat_id, text))

    async def send_photo(self, chat_id, photo=None, caption=None, **kwargs):
        SENT.append(("photo", chat_id, caption))

    async def send_document(self, chat_id, document=None, caption=None, **kwargs):
        SENT.append(("document", chat_id, caption))


class FakeContext:
    def __init__(self):
        self.user_data = {}
        self.args = []
        self.bot = FakeBot()


class FakePhotoSize:
    file_id = "test_photo_file_id"


# ---------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------

def eq(got, want, label):
    assert got == want, f"{label}: got {got!r}, want {want!r}"


def sent_text():
    """Every outgoing string, flattened, for substring assertions."""
    return " | ".join(str(part) for entry in SENT for part in entry[1:])


# ---------------------------------------------------------------------
# db.py
# ---------------------------------------------------------------------

def test_registration_and_integrity():
    eq(db.register_tutor("T1", "Meron", "Math"), (True, None), "register tutor")

    ok, err = db.register_student("S1", "Abel", "NOPE")
    assert ok is False and "does not exist" in err, "unknown tutor must be refused"
    eq(db.register_student("S1", "Abel", "T1"), (True, None), "register student")

    ok, err = db.register_parent("P9", "Ghost", "NOPE")
    assert ok is False, "parent of an unknown student must be refused"
    eq(db.register_parent("P1", "Tigist", "S1"), (True, None), "register parent")

    eq(db.register_student("S2", "Hana"), (True, None), "second student")
    eq(db.link_parent_child("P1", "S2"), (True, None), "second child")
    eq(len(db.get_children("P1")), 2, "parent has two children")


def test_tutor_approval_gate():
    row, err = db.link_tutor("T1", 500)
    assert row is None and err == "unapproved", "unapproved tutor must not log in"
    assert db.approve_tutor("T1"), "approve"
    row, err = db.link_tutor("T1", 500)
    assert row is not None and err is None, "approved tutor logs in"


def test_account_linking_rules():
    row, err = db.link_student("S1", 600)
    assert row is not None and err is None, "first login links the account"

    eq(db.link_student("S1", 601)[1], "claimed", "another Telegram user cannot take an ID")
    eq(db.link_student("NOPE", 602)[1], "not_found", "unknown ID")
    eq(db.link_student("S2", 600)[1], "other_account", "one Telegram account, one record")

    db.link_parent("P1", 700)


def test_authorization():
    eq(db.register_student("S9", "Outsider"), (True, None), "unassigned student")
    assert db.tutor_teaches("T1", "S1"), "assigned"
    assert not db.tutor_teaches("T1", "S9"), "not assigned"


def test_parsing():
    eq(db.parse_score("85"), ((85, 100), None), "plain score")
    eq(db.parse_score("85/120"), ((85, 120), None), "score out of max")
    assert db.parse_score("130/120")[0] is None, "score above max"
    assert db.parse_score("abc")[0] is None, "non-numeric score"
    assert db.parse_score("85/0")[0] is None, "zero max"

    eq(db.parse_amount("1,200.50"), (1200.50, None), "thousands separator")
    eq(db.parse_amount("ETB 500"), (500.0, None), "currency prefix")
    assert db.parse_amount("-5")[0] is None, "negative amount"
    assert db.parse_amount("nope")[0] is None, "non-numeric amount"

    eq(db.parse_date(FUTURE), (FUTURE, None), "future date")
    assert db.parse_date("2020-01-01")[0] is None, "past date"
    assert db.parse_date("15/09/2026")[0] is None, "wrong format"


def test_results_and_performance():
    db.add_result("S1", "Math", 90, 100, "T1")
    db.add_result("S1", "Math", 70, 100, "T1")
    overall, per_subject = db.get_performance("S1")
    eq(overall["n"], 2, "result count")
    assert abs(overall["pct"] - 80.0) < 1e-9, f"average: {overall['pct']}"
    eq(per_subject[0]["subject"], "Math", "per-subject breakdown")


def test_sessions_ignore_the_past():
    db.add_session("S1", "T1", "Old topic", "2020-01-01")
    assert db.get_next_session("S1") is None, "a past session is not the next one"
    db.add_session("S1", "T1", "Quadratics", FUTURE)
    nxt = db.get_next_session("S1")
    eq(nxt["topic"], "Quadratics", "next session topic")
    eq(nxt["tutor_name"], "Meron", "next session tutor")


def test_payment_decided_only_once():
    pid = db.submit_payment("parent", "P1", "S1", 500.0, "ETB", "file123", "photo")
    eq(db.set_payment_status(pid, "approved", 111), (True, None), "first decision")
    ok, err = db.set_payment_status(pid, "rejected", 111)
    assert ok is False and "already approved" in err, f"second decision: {err}"
    assert db.set_payment_status(9999, "approved", 111)[0] is False, "unknown payment"
    assert db.set_payment_status(pid, "bogus", 111)[0] is False, "invalid status"


def test_status_validation():
    assert db.set_student_status("S1", "nonsense")[0] is False, "invalid status"
    eq(db.set_student_status("S1", "graduated"), (True, None), "valid status")
    eq(db.get_student("S1")["status"], "graduated", "status persisted")
    assert db.set_student_status("NOPE", "active")[0] is False, "unknown student"
    db.set_student_status("S1", "active")


def test_init_db_is_idempotent():
    db.init_db()
    eq(db.get_student("S1")["name"], "Abel", "data survives re-init")


# ---------------------------------------------------------------------
# bot.py conversation flows
# ---------------------------------------------------------------------

async def test_tutor_grade_flow():
    ctx = FakeContext()
    eq(await bot.start(FakeUpdate(500), ctx), bot.ROLE, "tutor /start")
    eq(await bot.choose_role(FakeUpdate(500, data="role_tutor"), ctx), bot.TUTOR_ID, "pick role")
    eq(await bot.tutor_id_entered(FakeUpdate(500, text="T1"), ctx), bot.MENU, "tutor login")
    eq(await bot.menu_action(FakeUpdate(500, data="t_students"), ctx), bot.MENU, "view students")

    eq(await bot.menu_action(FakeUpdate(500, data="t_grade"), ctx),
       bot.GRADE_STUDENT, "start grading")
    eq(await bot.tutor_grade_student(FakeUpdate(500, data="gs_S1"), ctx),
       bot.GRADE_SUBJECT, "pick student")
    eq(await bot.tutor_grade_subject(FakeUpdate(500, text="Physics"), ctx),
       bot.GRADE_SCORE, "enter subject")
    eq(await bot.tutor_grade_score(FakeUpdate(500, text="not a score"), ctx),
       bot.GRADE_SCORE, "bad score re-asks")
    eq(await bot.tutor_grade_score(FakeUpdate(500, text="85/120"), ctx), bot.MENU, "record score")
    assert any(r["score"] == 85 and r["max_score"] == 120 and r["subject"] == "Physics"
               for r in db.get_results("S1")), "grade stored"

    SENT.clear()
    eq(await bot.tutor_grade_student(FakeUpdate(500, data="gs_S9"), ctx),
       bot.MENU, "unassigned student refused")
    assert "not assigned" in sent_text(), sent_text()


async def test_tutor_topic_notifies_student_and_parent():
    ctx = FakeContext()
    await bot.choose_role(FakeUpdate(500, data="role_tutor"), ctx)
    await bot.tutor_id_entered(FakeUpdate(500, text="T1"), ctx)

    eq(await bot.menu_action(FakeUpdate(500, data="t_topic"), ctx),
       bot.TOPIC_STUDENT, "start topic")
    eq(await bot.tutor_topic_student(FakeUpdate(500, data="ts_S1"), ctx),
       bot.TOPIC_TEXT, "pick student")
    eq(await bot.tutor_topic_text(FakeUpdate(500, text="Trigonometry"), ctx),
       bot.TOPIC_DATE, "enter topic")
    eq(await bot.tutor_topic_date(FakeUpdate(500, text="2020-01-01"), ctx),
       bot.TOPIC_DATE, "past date re-asks")

    SENT.clear()
    eq(await bot.tutor_topic_date(FakeUpdate(500, text=FUTURE), ctx), bot.MENU, "save session")
    notified = {entry[1] for entry in SENT if entry[0] == "dm"}
    eq(notified, {600, 700}, "student and parent both notified")


async def test_student_menu():
    ctx = FakeContext()
    await bot.choose_role(FakeUpdate(600, data="role_student"), ctx)
    eq(await bot.student_id_entered(FakeUpdate(600, text="S1"), ctx), bot.MENU, "student login")
    for action in ("s_results", "s_session", "s_status"):
        eq(await bot.menu_action(FakeUpdate(600, data=action), ctx), bot.MENU, action)

    SENT.clear()
    eq(await bot.menu_action(FakeUpdate(600, data="a_users"), ctx), bot.MENU, "stale admin button")
    assert "isn't available for your role" in sent_text(), sent_text()


async def test_parent_payment_flow():
    ctx = FakeContext()
    await bot.choose_role(FakeUpdate(700, data="role_parent"), ctx)
    eq(await bot.parent_id_entered(FakeUpdate(700, text="P1"), ctx), bot.MENU, "parent login")
    for action in ("p_grades", "p_perf", "p_contact"):
        eq(await bot.menu_action(FakeUpdate(700, data=action), ctx), bot.MENU, action)

    # Two children, so the parent is asked which one first.
    eq(await bot.menu_action(FakeUpdate(700, data="pay_start"), ctx), bot.PAY_CHILD, "pay start")
    eq(await bot.pay_child(FakeUpdate(700, data="pc_S1"), ctx), bot.PAY_AMOUNT, "pick child")
    eq(await bot.pay_amount(FakeUpdate(700, text="nope"), ctx), bot.PAY_AMOUNT, "bad amount")
    eq(await bot.pay_amount(FakeUpdate(700, text="1,200.50"), ctx), bot.PAY_RECEIPT, "amount")
    eq(await bot.pay_receipt(FakeUpdate(700, text="text, not a file"), ctx),
       bot.PAY_RECEIPT, "receipt must be a file")

    SENT.clear()
    eq(await bot.pay_receipt(FakeUpdate(700, photo=[FakePhotoSize()]), ctx), bot.MENU, "receipt")
    assert any(e[0] == "photo" and e[1] == 111 for e in SENT), f"admin not notified: {SENT}"
    pending = db.get_pending_payments()
    assert abs(pending[0]["amount"] - 1200.50) < 1e-9, "amount stored"
    return pending[0]["id"]


async def test_admin_menu_and_review(payment_id):
    ctx = FakeContext()
    eq(await bot.start(FakeUpdate(111), ctx), bot.MENU, "admin skips login")
    for action in ("a_users", "a_payments", "a_help", "a_pending", "a_tutors"):
        eq(await bot.menu_action(FakeUpdate(111, data=action), ctx), bot.MENU, action)

    SENT.clear()
    await bot.review_payment(FakeUpdate(111, data=f"rev_approve_{payment_id}"), ctx)
    eq(db.get_payment(payment_id)["status"], "approved", "payment approved")
    assert any(e[0] == "dm" and e[1] == 700 for e in SENT), f"submitter not told: {SENT}"

    SENT.clear()
    await bot.review_payment(FakeUpdate(111, data=f"rev_reject_{payment_id}"), ctx)
    assert "already approved" in sent_text(), sent_text()

    SENT.clear()
    await bot.review_payment(FakeUpdate(999, data=f"rev_approve_{payment_id}"), ctx)
    assert not SENT, "a non-admin must not be able to decide a payment"

    db.register_tutor("T2", "Samuel", "Physics")
    eq(await bot.approve_tutor_button(FakeUpdate(111, data="tap_T2"), ctx), bot.MENU, "approve")
    eq(db.get_tutor("T2")["approved"], 1, "tutor approved via button")


async def test_admin_commands():
    ctx = FakeContext()
    ctx.args = ["S5", "Newkid"]
    await bot.register_student_cmd(FakeUpdate(111), ctx)
    eq(db.get_student("S5")["name"], "Newkid", "student registered by command")

    ctx.args = ["S5", "graduated"]
    await bot.set_status_cmd(FakeUpdate(111), ctx)
    eq(db.get_student("S5")["status"], "graduated", "status set by command")

    # Usage strings must name real commands.
    for func, expected in ((bot.approve_payment_cmd, "/approve_payment"),
                           (bot.reject_payment_cmd, "/reject_payment")):
        ctx.args = []
        SENT.clear()
        await func(FakeUpdate(111), ctx)
        assert expected in sent_text(), f"usage string: {sent_text()}"

    ctx.args = ["S6", "Sneaky"]
    SENT.clear()
    await bot.register_student_cmd(FakeUpdate(999), ctx)
    assert db.get_student("S6") is None, "non-admin must not register anyone"
    assert "admins only" in sent_text().lower(), sent_text()


async def test_expired_session_restarts():
    eq(await bot.menu_action(FakeUpdate(600, data="s_results"), FakeContext()),
       ConversationHandler.END, "lost user_data ends the conversation")


def test_app_builds():
    app = bot.build_app()
    assert sum(len(group) for group in app.handlers.values()) > 0, "handlers wired"


# ---------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------

async def main():
    db.init_db()
    db.seed_admins({111})

    for test in (
        test_registration_and_integrity,
        test_tutor_approval_gate,
        test_account_linking_rules,
        test_authorization,
        test_parsing,
        test_results_and_performance,
        test_sessions_ignore_the_past,
        test_payment_decided_only_once,
        test_status_validation,
        test_init_db_is_idempotent,
    ):
        test()
        print(f"  ok  {test.__name__}")

    for test in (
        test_tutor_grade_flow,
        test_tutor_topic_notifies_student_and_parent,
        test_student_menu,
    ):
        await test()
        print(f"  ok  {test.__name__}")

    payment_id = await test_parent_payment_flow()
    print("  ok  test_parent_payment_flow")

    await test_admin_menu_and_review(payment_id)
    print("  ok  test_admin_menu_and_review")

    for test in (test_admin_commands, test_expired_session_restarts):
        await test()
        print(f"  ok  {test.__name__}")

    test_app_builds()
    print("  ok  test_app_builds")

    print("\nAll tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
