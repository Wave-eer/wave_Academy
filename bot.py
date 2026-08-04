"""Wave Academy Telegram bot.

Every multi-step flow runs inside a single ConversationHandler, so an
unexpected message never leaves a user stranded mid-flow. Menus use inline
keyboards (buttons) rather than "reply with 1, 2, 3", which removes a whole
class of invalid input.

Roles
    Student  view results, next session, my status, submit receipt
    Parent   child's grades, performance, contact teacher, submit receipt
    Tutor    enter grades, update study topics, view students (needs approval)
    Admin    manage users, approve tutors, review payments

Run:
    python bot.py
"""

import html
import logging

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import db
from config import DEFAULT_CURRENCY, require_admins, require_token

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Conversation states
(
    ROLE,
    STUDENT_ID, PARENT_ID, TUTOR_ID,
    MENU,
    GRADE_STUDENT, GRADE_SUBJECT, GRADE_SCORE,
    TOPIC_STUDENT, TOPIC_TEXT, TOPIC_DATE,
    PAY_CHILD, PAY_AMOUNT, PAY_RECEIPT,
) = range(14)

MAX_TEXT = 200  # cap free-text fields (subject, topic) to keep messages sane


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""))


def money(amount) -> str:
    """A row migrated from the old schema can have no amount — show it, don't crash."""
    return f"{amount:.2f}" if amount is not None else "?"


# ---------------------------------------------------------------------
# Menus
# ---------------------------------------------------------------------

STUDENT_MENU = [
    [InlineKeyboardButton("📊 View Results", callback_data="s_results")],
    [InlineKeyboardButton("📅 Next Study Session", callback_data="s_session")],
    [InlineKeyboardButton("ℹ️ My Status", callback_data="s_status")],
    [InlineKeyboardButton("💵 Submit Payment Receipt", callback_data="pay_start")],
    [InlineKeyboardButton("🚪 Log out", callback_data="logout")],
]
PARENT_MENU = [
    [InlineKeyboardButton("📊 Child Grades", callback_data="p_grades")],
    [InlineKeyboardButton("📈 Performance Status", callback_data="p_perf")],
    [InlineKeyboardButton("👨‍🏫 Contact Teacher", callback_data="p_contact")],
    [InlineKeyboardButton("💵 Submit Payment Receipt", callback_data="pay_start")],
    [InlineKeyboardButton("🚪 Log out", callback_data="logout")],
]
TUTOR_MENU = [
    [InlineKeyboardButton("📝 Enter Grades", callback_data="t_grade")],
    [InlineKeyboardButton("📚 Update Study Topics", callback_data="t_topic")],
    [InlineKeyboardButton("👥 View Students", callback_data="t_students")],
    [InlineKeyboardButton("🚪 Log out", callback_data="logout")],
]
ADMIN_MENU = [
    [InlineKeyboardButton("👥 View Users", callback_data="a_users")],
    [InlineKeyboardButton("✅ Approve Tutors", callback_data="a_tutors")],
    [InlineKeyboardButton("💵 All Payments", callback_data="a_payments")],
    [InlineKeyboardButton("🕒 Pending Payments", callback_data="a_pending")],
    [InlineKeyboardButton("❓ Admin Commands", callback_data="a_help")],
    [InlineKeyboardButton("🚪 Log out", callback_data="logout")],
]

MENUS = {
    "student": (STUDENT_MENU, "🎓 Student menu"),
    "parent": (PARENT_MENU, "👨‍👩‍👧 Parent menu"),
    "tutor": (TUTOR_MENU, "👨‍🏫 Tutor menu"),
    "admin": (ADMIN_MENU, "🛠 Admin menu"),
}


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, note=None):
    """Send the menu for the current role. Always returns the MENU state."""
    role = context.user_data.get("role")
    if role not in MENUS:
        return await force_restart(update)
    keyboard, title = MENUS[role]
    text = f"{note}\n\n{title}" if note else title
    target = update.effective_message
    await target.reply_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML
    )
    return MENU


async def force_restart(update: Update):
    await update.effective_message.reply_text(
        "Your session expired. Send /start to log in again."
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------
# Entry: /start and role selection
# ---------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user = update.effective_user

    # An admin skips ID entry — their Telegram ID is the credential.
    if db.is_admin(user.id):
        context.user_data["role"] = "admin"
        return await show_menu(
            update, context, f"👋 Welcome back, {esc(user.first_name)} (admin)."
        )

    keyboard = [
        [InlineKeyboardButton("🎓 Student", callback_data="role_student")],
        [InlineKeyboardButton("👨‍👩‍👧 Parent", callback_data="role_parent")],
        [InlineKeyboardButton("👨‍🏫 Tutor", callback_data="role_tutor")],
    ]
    await update.effective_message.reply_text(
        "👋 <b>Welcome to Wave Academy!</b>\n\nWho are you?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML,
    )
    return ROLE


async def choose_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    role = query.data.removeprefix("role_")
    context.user_data["role"] = role
    prompts = {
        "student": ("🎓 Student", "Student ID", STUDENT_ID),
        "parent": ("👨‍👩‍👧 Parent", "Parent ID", PARENT_ID),
        "tutor": ("👨‍🏫 Tutor", "Tutor ID", TUTOR_ID),
    }
    label, id_name, state = prompts[role]
    await query.edit_message_text(
        f"{label} selected.\n\nEnter your <b>{id_name}</b>.\n"
        "<i>Send /cancel to start over.</i>",
        parse_mode=ParseMode.HTML,
    )
    return state


LINK_ERRORS = {
    "not_found": "❌ That ID is not registered. Please check it, or ask an admin to register you.",
    "claimed": "⛔ That ID is already linked to a different Telegram account. Contact an admin.",
    "other_account": "⛔ Your Telegram account is already linked to a different ID.",
    "unapproved": "⏳ Your tutor account is awaiting admin approval. You'll be able to log in once approved.",
}


async def student_id_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    student_id = update.message.text.strip()
    row, err = db.link_student(student_id, update.effective_user.id)
    if err:
        await update.message.reply_text(LINK_ERRORS[err])
        return ConversationHandler.END if err != "not_found" else STUDENT_ID
    context.user_data.update(student_id=student_id, name=row["name"])
    return await show_menu(update, context, f"✅ Welcome, <b>{esc(row['name'])}</b>!")


async def parent_id_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parent_id = update.message.text.strip()
    row, err = db.link_parent(parent_id, update.effective_user.id)
    if err:
        await update.message.reply_text(LINK_ERRORS[err])
        return ConversationHandler.END if err != "not_found" else PARENT_ID
    context.user_data.update(parent_id=parent_id, name=row["name"])
    children = db.get_children(parent_id)
    note = f"✅ Welcome, <b>{esc(row['name'])}</b>!"
    if not children:
        note += "\n\n⚠️ No child is linked to your account yet — ask an admin."
    return await show_menu(update, context, note)


async def tutor_id_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tutor_id = update.message.text.strip()
    row, err = db.link_tutor(tutor_id, update.effective_user.id)
    if err:
        await update.message.reply_text(LINK_ERRORS[err])
        return ConversationHandler.END if err != "not_found" else TUTOR_ID
    context.user_data.update(tutor_id=tutor_id, name=row["name"])
    return await show_menu(update, context, f"✅ Welcome, <b>{esc(row['name'])}</b>!")


# ---------------------------------------------------------------------
# Menu dispatch
# ---------------------------------------------------------------------

async def menu_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data
    role = context.user_data.get("role")
    if role is None:
        return await force_restart(update)

    if action == "logout":
        context.user_data.clear()
        await query.edit_message_text("👋 Logged out. Send /start to log in again.")
        return ConversationHandler.END

    handlers = {
        "s_results": student_results, "s_session": student_session,
        "s_status": student_status,
        "p_grades": parent_grades, "p_perf": parent_performance,
        "p_contact": parent_contact,
        "t_grade": tutor_grade_start, "t_topic": tutor_topic_start,
        "t_students": tutor_students,
        "a_users": admin_users, "a_tutors": admin_tutors,
        "a_payments": admin_payments, "a_pending": admin_pending,
        "a_help": admin_help,
        "pay_start": pay_start,
    }
    # Guard against a stale button from a previous role's menu.
    allowed = {"student": "s_", "parent": "p_", "tutor": "t_", "admin": "a_"}[role]
    if not (action.startswith(allowed) or action == "pay_start"):
        await query.edit_message_text("⛔ That option isn't available for your role.")
        return await show_menu(update, context)
    if action == "pay_start" and role not in ("student", "parent"):
        await query.edit_message_text("⛔ Only students and parents submit receipts.")
        return await show_menu(update, context)

    return await handlers[action](update, context)


# ---------------------------------------------------------------------
# Student actions
# ---------------------------------------------------------------------

def format_results(rows):
    lines = []
    for r in rows:
        pct = f" ({r['score'] * 100 // r['max_score']}%)" if r["max_score"] else ""
        stamp = str(r["recorded_at"])[:10]
        lines.append(f"• <b>{esc(r['subject'])}</b>: {r['score']}/{r['max_score']}{pct} — {stamp}")
    return "\n".join(lines)


async def student_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.get_results(context.user_data["student_id"])
    text = "📊 <b>Your results</b>\n\n" + format_results(rows) if rows \
        else "📊 No results recorded yet."
    return await show_menu(update, context, text)


async def student_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = db.get_next_session(context.user_data["student_id"])
    if s is None:
        text = "📅 No upcoming session scheduled yet."
    else:
        tutor = f"\nTutor: {esc(s['tutor_name'])}" if s["tutor_name"] else ""
        text = (f"📅 <b>Next session</b>\n\nDate: {esc(s['session_date'])}\n"
                f"Topic: {esc(s['topic'])}{tutor}")
    return await show_menu(update, context, text)


async def student_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    student = db.get_student(context.user_data["student_id"])
    if student is None:
        return await force_restart(update)
    overall, _ = db.get_performance(student["student_id"])
    avg = f"\nAverage: {overall['pct']:.1f}% across {overall['n']} result(s)" \
        if overall and overall["n"] else "\nNo grades recorded yet."
    payments = db.get_payments_for_submitter("student", student["student_id"], limit=3)
    pay_line = ""
    if payments:
        pay_line = "\n\n<b>Recent receipts</b>\n" + "\n".join(
            f"• #{p['id']} {money(p['amount'])} {esc(p['currency'])} — {esc(p['status'])}"
            for p in payments
        )
    text = (f"ℹ️ <b>Your status</b>\n\nName: {esc(student['name'])}\n"
            f"Enrollment: <b>{esc(student['status'])}</b>{avg}{pay_line}")
    return await show_menu(update, context, text)


# ---------------------------------------------------------------------
# Parent actions
# ---------------------------------------------------------------------

def children_or_note(context):
    children = db.get_children(context.user_data["parent_id"])
    return children, None if children else "⚠️ No child is linked to your account yet."


async def parent_grades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    children, note = children_or_note(context)
    if note:
        return await show_menu(update, context, note)
    blocks = []
    for child in children:
        rows = db.get_results(child["student_id"])
        body = format_results(rows) if rows else "<i>No results recorded yet.</i>"
        blocks.append(f"👤 <b>{esc(child['name'])}</b>\n{body}")
    return await show_menu(update, context, "📊 <b>Grades</b>\n\n" + "\n\n".join(blocks))


async def parent_performance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    children, note = children_or_note(context)
    if note:
        return await show_menu(update, context, note)
    blocks = []
    for child in children:
        overall, per_subject = db.get_performance(child["student_id"])
        if not overall or not overall["n"]:
            blocks.append(f"👤 <b>{esc(child['name'])}</b>\n<i>No grades yet.</i>")
            continue
        pct = overall["pct"]
        verdict = ("🌟 Excellent" if pct >= 80 else "👍 Good" if pct >= 65
                   else "📚 Needs attention" if pct >= 50 else "⚠️ At risk")
        subjects = "\n".join(
            f"   • {esc(s['subject'])}: {s['pct']:.1f}%" for s in per_subject
        )
        blocks.append(
            f"👤 <b>{esc(child['name'])}</b>\nOverall: {pct:.1f}% — {verdict}\n"
            f"Status: {esc(child['status'])}\n{subjects}"
        )
    return await show_menu(update, context, "📈 <b>Performance</b>\n\n" + "\n\n".join(blocks))


async def parent_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    children, note = children_or_note(context)
    if note:
        return await show_menu(update, context, note)
    blocks = []
    for child in children:
        tutors = db.get_tutors_for_student(child["student_id"])
        if not tutors:
            blocks.append(f"👤 <b>{esc(child['name'])}</b>\n<i>No tutor assigned yet.</i>")
            continue
        lines = []
        for t in tutors:
            phone = f"\n   📞 {esc(t['phone'])}" if t["phone"] else ""
            lines.append(f"   👨‍🏫 {esc(t['name'])} — {esc(t['subject'] or 'general')}{phone}")
        blocks.append(f"👤 <b>{esc(child['name'])}</b>\n" + "\n".join(lines))
    return await show_menu(
        update, context,
        "👨‍🏫 <b>Teachers</b>\n\n" + "\n\n".join(blocks) +
        "\n\n<i>Ask an admin if a phone number is missing.</i>",
    )


# ---------------------------------------------------------------------
# Tutor actions
# ---------------------------------------------------------------------

async def tutor_students(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.get_students_for_tutor(context.user_data["tutor_id"])
    if not rows:
        return await show_menu(update, context, "👥 No students assigned to you yet.")
    lines = [
        f"• <code>{esc(r['student_id'])}</code> — {esc(r['name'])} "
        f"({esc(r['status'])}{', ' + esc(r['subject']) if r['subject'] else ''})"
        for r in rows
    ]
    return await show_menu(update, context, "👥 <b>Your students</b>\n\n" + "\n".join(lines))


def student_picker(tutor_id, prefix):
    rows = db.get_students_for_tutor(tutor_id)
    if not rows:
        return None
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"{r['name']} ({r['student_id']})",
                               callback_data=f"{prefix}{r['student_id']}")]
         for r in rows]
        + [[InlineKeyboardButton("◀️ Back", callback_data=f"{prefix}__back")]]
    )


async def tutor_grade_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = student_picker(context.user_data["tutor_id"], "gs_")
    if keyboard is None:
        return await show_menu(update, context, "👥 No students assigned to you yet.")
    await update.callback_query.edit_message_text(
        "📝 Which student are you grading?", reply_markup=keyboard
    )
    return GRADE_STUDENT


async def tutor_grade_student(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    student_id = query.data.removeprefix("gs_")
    if student_id == "__back":
        await query.edit_message_text("Cancelled.")
        return await show_menu(update, context)
    # Re-check authorization: the assignment may have changed since the menu was drawn.
    if not db.tutor_teaches(context.user_data["tutor_id"], student_id):
        await query.edit_message_text("⛔ You are not assigned to that student.")
        return await show_menu(update, context)
    context.user_data["grade_student"] = student_id
    await query.edit_message_text(
        f"📝 Grading <code>{esc(student_id)}</code>.\n\nEnter the <b>subject</b>:",
        parse_mode=ParseMode.HTML,
    )
    return GRADE_SUBJECT


async def tutor_grade_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subject = update.message.text.strip()
    if not 1 <= len(subject) <= MAX_TEXT:
        await update.message.reply_text(f"Subject must be 1–{MAX_TEXT} characters.")
        return GRADE_SUBJECT
    context.user_data["grade_subject"] = subject
    await update.message.reply_text(
        "Enter the <b>score</b> — e.g. <code>85</code> or <code>85/120</code>:",
        parse_mode=ParseMode.HTML,
    )
    return GRADE_SCORE


async def tutor_grade_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parsed, err = db.parse_score(update.message.text)
    if err:
        await update.message.reply_text(f"❗ {err}")
        return GRADE_SCORE
    score, max_score = parsed
    db.add_result(
        context.user_data["grade_student"], context.user_data["grade_subject"],
        score, max_score, context.user_data["tutor_id"],
    )
    return await show_menu(
        update, context,
        f"✅ Recorded: <b>{esc(context.user_data['grade_subject'])}</b> "
        f"{score}/{max_score} for <code>{esc(context.user_data['grade_student'])}</code>.",
    )


async def tutor_topic_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = student_picker(context.user_data["tutor_id"], "ts_")
    if keyboard is None:
        return await show_menu(update, context, "👥 No students assigned to you yet.")
    await update.callback_query.edit_message_text(
        "📚 Which student is this session for?", reply_markup=keyboard
    )
    return TOPIC_STUDENT


async def tutor_topic_student(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    student_id = query.data.removeprefix("ts_")
    if student_id == "__back":
        await query.edit_message_text("Cancelled.")
        return await show_menu(update, context)
    if not db.tutor_teaches(context.user_data["tutor_id"], student_id):
        await query.edit_message_text("⛔ You are not assigned to that student.")
        return await show_menu(update, context)
    context.user_data["topic_student"] = student_id
    await query.edit_message_text(
        f"📚 Session for <code>{esc(student_id)}</code>.\n\nEnter the <b>topic</b>:",
        parse_mode=ParseMode.HTML,
    )
    return TOPIC_TEXT


async def tutor_topic_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = update.message.text.strip()
    if not 1 <= len(topic) <= MAX_TEXT:
        await update.message.reply_text(f"Topic must be 1–{MAX_TEXT} characters.")
        return TOPIC_TEXT
    context.user_data["topic_text"] = topic
    await update.message.reply_text(
        "Enter the <b>session date</b> as YYYY-MM-DD (e.g. 2026-09-15):",
        parse_mode=ParseMode.HTML,
    )
    return TOPIC_DATE


async def tutor_topic_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    iso, err = db.parse_date(update.message.text)
    if err:
        await update.message.reply_text(f"❗ {err}")
        return TOPIC_DATE
    db.add_session(
        context.user_data["topic_student"], context.user_data["tutor_id"],
        context.user_data["topic_text"], iso,
    )
    # Tell the student, and their parents, that a session was scheduled.
    student_id = context.user_data["topic_student"]
    student = db.get_student(student_id)
    recipients = []
    if student and student["telegram_id"]:
        recipients.append(student["telegram_id"])
    recipients += [
        p["telegram_id"] for p in db.get_parents_for_student(student_id)
        if p["telegram_id"]
    ]
    for tid in recipients:
        try:
            await context.bot.send_message(
                tid,
                f"📅 New session scheduled for <b>{esc(iso)}</b>\n"
                f"Student: {esc(student['name'] if student else student_id)}\n"
                f"Topic: {esc(context.user_data['topic_text'])}",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            logger.warning("Could not notify %s about a new session", tid)

    return await show_menu(
        update, context,
        f"✅ Session saved for <code>{esc(student_id)}</code> on {esc(iso)}.",
    )


# ---------------------------------------------------------------------
# Payment receipts (student or parent)
# ---------------------------------------------------------------------

async def pay_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    role = context.user_data["role"]
    if role == "student":
        context.user_data["pay_student"] = context.user_data["student_id"]
        await update.callback_query.edit_message_text(
            f"💵 Enter the <b>amount paid</b> in {DEFAULT_CURRENCY} (e.g. 500):",
            parse_mode=ParseMode.HTML,
        )
        return PAY_AMOUNT

    children = db.get_children(context.user_data["parent_id"])
    if not children:
        return await show_menu(
            update, context, "⚠️ No child is linked to your account, so there's nothing to pay for."
        )
    if len(children) == 1:
        context.user_data["pay_student"] = children[0]["student_id"]
        await update.callback_query.edit_message_text(
            f"💵 Payment for <b>{esc(children[0]['name'])}</b>.\n\n"
            f"Enter the <b>amount paid</b> in {DEFAULT_CURRENCY} (e.g. 500):",
            parse_mode=ParseMode.HTML,
        )
        return PAY_AMOUNT

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(c["name"], callback_data=f"pc_{c['student_id']}")]
         for c in children]
        + [[InlineKeyboardButton("◀️ Back", callback_data="pc___back")]]
    )
    await update.callback_query.edit_message_text(
        "💵 Which child is this payment for?", reply_markup=keyboard
    )
    return PAY_CHILD


async def pay_child(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    student_id = query.data.removeprefix("pc_")
    if student_id == "__back":
        await query.edit_message_text("Cancelled.")
        return await show_menu(update, context)
    context.user_data["pay_student"] = student_id
    await query.edit_message_text(
        f"💵 Enter the <b>amount paid</b> in {DEFAULT_CURRENCY} (e.g. 500):",
        parse_mode=ParseMode.HTML,
    )
    return PAY_AMOUNT


async def pay_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount, err = db.parse_amount(update.message.text)
    if err:
        await update.message.reply_text(f"❗ {err}")
        return PAY_AMOUNT
    context.user_data["pay_amount"] = amount
    await update.message.reply_text(
        f"📎 Now send the receipt as a <b>photo</b> or a <b>document</b> "
        f"(PDF/image).\n\n<i>Send /cancel to abandon this submission.</i>",
        parse_mode=ParseMode.HTML,
    )
    return PAY_RECEIPT


async def pay_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.photo:
        file_id, kind = msg.photo[-1].file_id, "photo"
    elif msg.document:
        file_id, kind = msg.document.file_id, "document"
    else:
        await msg.reply_text("❗ Please send the receipt as a photo or a document.")
        return PAY_RECEIPT

    role = context.user_data["role"]
    submitter_id = context.user_data["parent_id" if role == "parent" else "student_id"]
    student_id = context.user_data["pay_student"]
    amount = context.user_data["pay_amount"]

    payment_id = db.submit_payment(
        role, submitter_id, student_id, amount, DEFAULT_CURRENCY,
        file_id, kind, note=msg.caption,
    )

    student = db.get_student(student_id)
    caption = (
        f"💵 <b>New receipt #{payment_id}</b>\n\n"
        f"From: {esc(context.user_data.get('name'))} ({role} <code>{esc(submitter_id)}</code>)\n"
        f"Student: {esc(student['name'] if student else student_id)}\n"
        f"Amount: <b>{amount:.2f} {DEFAULT_CURRENCY}</b>"
    )
    buttons = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"rev_approve_{payment_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"rev_reject_{payment_id}"),
    ]])

    delivered = 0
    for admin in db.list_admins():
        try:
            send = context.bot.send_photo if kind == "photo" else context.bot.send_document
            await send(chat_id=admin["telegram_id"], **{kind: file_id},
                       caption=caption, parse_mode=ParseMode.HTML, reply_markup=buttons)
            delivered += 1
        except Exception:
            logger.warning("Could not notify admin %s", admin["telegram_id"])

    note = f"✅ Receipt <b>#{payment_id}</b> submitted for review."
    if not delivered:
        note += "\n\n⚠️ No admin could be reached right now, but your receipt is saved."
        logger.error("Payment #%s reached no admin", payment_id)
    return await show_menu(update, context, note)


# ---------------------------------------------------------------------
# Admin actions
# ---------------------------------------------------------------------

async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    students, tutors, parents = db.list_students(), db.list_tutors(), db.list_parents()
    def block(title, rows, fmt):
        if not rows:
            return f"<b>{title}</b>\n<i>none</i>"
        return f"<b>{title}</b>\n" + "\n".join(fmt(r) for r in rows)
    text = "👥 <b>Users</b>\n\n" + "\n\n".join([
        block("Students", students,
              lambda r: f"• <code>{esc(r['student_id'])}</code> {esc(r['name'])} "
                        f"({esc(r['status'])}{'' if r['telegram_id'] else ', not linked'})"),
        block("Tutors", tutors,
              lambda r: f"• <code>{esc(r['tutor_id'])}</code> {esc(r['name'])} "
                        f"({esc(r['subject'] or '—')}{'' if r['approved'] else ', ⏳ pending'})"),
        block("Parents", parents,
              lambda r: f"• <code>{esc(r['parent_id'])}</code> {esc(r['name'])}"),
    ])
    return await show_menu(update, context, text)


async def admin_tutors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending = db.list_pending_tutors()
    if not pending:
        return await show_menu(update, context, "✅ No tutors are awaiting approval.")
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"✅ Approve {t['name']} ({t['tutor_id']})",
                               callback_data=f"tap_{t['tutor_id']}")]
         for t in pending]
    )
    await update.callback_query.edit_message_text(
        "⏳ <b>Tutors awaiting approval</b>", reply_markup=keyboard, parse_mode=ParseMode.HTML
    )
    return MENU


def format_payment(p):
    icon = {"pending": "🕒", "approved": "✅", "rejected": "❌"}.get(p["status"], "•")
    return (f"{icon} <b>#{p['id']}</b> {money(p['amount'])} {esc(p['currency'])} — "
            f"{esc(p['submitter_role'])} <code>{esc(p['submitter_id'])}</code> "
            f"for <code>{esc(p['student_id'])}</code> ({str(p['submitted_at'])[:16]})")


async def admin_payments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.get_all_payments()
    text = "💵 <b>All payments</b>\n\n" + "\n".join(format_payment(p) for p in rows) \
        if rows else "💵 No payments submitted yet."
    return await show_menu(update, context, text)


async def admin_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.get_pending_payments()
    if not rows:
        return await show_menu(update, context, "✅ No payments awaiting review.")
    await update.callback_query.edit_message_text(
        "🕒 <b>Pending payments</b>\n\n" + "\n".join(format_payment(p) for p in rows),
        parse_mode=ParseMode.HTML,
    )
    # Send each receipt with its own approve/reject buttons.
    for p in rows:
        buttons = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"rev_approve_{p['id']}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"rev_reject_{p['id']}"),
        ]])
        try:
            send = context.bot.send_photo if p["receipt_kind"] == "photo" \
                else context.bot.send_document
            await send(chat_id=update.effective_chat.id, **{p["receipt_kind"]: p["receipt_file_id"]},
                       caption=format_payment(p), parse_mode=ParseMode.HTML, reply_markup=buttons)
        except Exception:
            logger.warning("Could not re-send receipt #%s", p["id"])
    return await show_menu(update, context)


async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await show_menu(update, context, ADMIN_HELP_TEXT)


async def review_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Approve/reject button. Registered globally so it works from any state."""
    query = update.callback_query
    user_id = update.effective_user.id
    if not db.is_admin(user_id):
        await query.answer("⛔ Admins only.", show_alert=True)
        return
    await query.answer()

    _, decision, payment_id = query.data.split("_", 2)
    status = "approved" if decision == "approve" else "rejected"
    ok, err = db.set_payment_status(int(payment_id), status, user_id)
    if not ok:
        await query.edit_message_caption(
            caption=f"⚠️ {esc(err)}", parse_mode=ParseMode.HTML
        )
        return

    payment = db.get_payment(int(payment_id))
    verdict = "✅ APPROVED" if status == "approved" else "❌ REJECTED"
    try:
        await query.edit_message_caption(
            caption=f"{format_payment(payment)}\n\n<b>{verdict}</b> by you",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        await query.edit_message_text(f"{verdict} — payment #{payment_id}")

    # Tell the submitter the outcome.
    tid = db.get_submitter_telegram_id(payment["submitter_role"], payment["submitter_id"])
    if tid:
        try:
            await context.bot.send_message(
                tid,
                f"{verdict}\n\nYour receipt #{payment_id} for "
                f"{money(payment['amount'])} {esc(payment['currency'])} was "
                f"{esc(status)} by an admin.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            logger.warning("Could not notify submitter of payment #%s", payment_id)


async def approve_tutor_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not db.is_admin(update.effective_user.id):
        await query.answer("⛔ Admins only.", show_alert=True)
        return MENU
    await query.answer()
    tutor_id = query.data.removeprefix("tap_")
    ok = db.approve_tutor(tutor_id)
    tutor = db.get_tutor(tutor_id)
    if ok and tutor and tutor["telegram_id"]:
        try:
            await context.bot.send_message(
                tutor["telegram_id"],
                "✅ Your tutor account has been approved. Send /start to log in.",
            )
        except Exception:
            logger.warning("Could not notify tutor %s of approval", tutor_id)
    return await show_menu(
        update, context,
        f"✅ Tutor <code>{esc(tutor_id)}</code> approved." if ok
        else f"❌ Tutor <code>{esc(tutor_id)}</code> not found.",
    )


# ---------------------------------------------------------------------
# Admin slash commands
# ---------------------------------------------------------------------

ADMIN_HELP_TEXT = (
    "🛠 <b>Admin commands</b>\n\n"
    "<code>/register_student &lt;id&gt; &lt;name&gt; [tutor_id]</code>\n"
    "<code>/register_parent &lt;id&gt; &lt;name&gt; [student_id]</code>\n"
    "<code>/register_tutor &lt;id&gt; &lt;name&gt; [subject]</code>\n"
    "<code>/approve_tutor &lt;tutor_id&gt;</code>\n"
    "<code>/assign_tutor &lt;tutor_id&gt; &lt;student_id&gt; [subject]</code>\n"
    "<code>/link_child &lt;parent_id&gt; &lt;student_id&gt;</code>\n"
    "<code>/set_status &lt;student_id&gt; &lt;active|inactive|suspended|graduated&gt;</code>\n"
    "<code>/add_admin &lt;telegram_id&gt;</code>\n"
    "<code>/pending_payments</code> · <code>/all_payments</code>\n"
    "<code>/approve_payment &lt;id&gt;</code> · <code>/reject_payment &lt;id&gt;</code>\n"
    "<code>/myid</code> — show your Telegram ID"
)


def admin_command(func):
    """Reject non-admins before the command body runs."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not db.is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ This command is for admins only.")
            return
        try:
            return await func(update, context)
        except db.DatabaseError:
            await update.message.reply_text("⚠️ Database error — please try again.")
    wrapper.__name__ = func.__name__
    return wrapper


async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Your Telegram ID is <code>{update.effective_user.id}</code>",
        parse_mode=ParseMode.HTML,
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if db.is_admin(update.effective_user.id):
        await update.message.reply_text(ADMIN_HELP_TEXT, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text("Send /start to log in. /cancel ends a session.")


@admin_command
async def admin_help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(ADMIN_HELP_TEXT, parse_mode=ParseMode.HTML)


@admin_command
async def register_student_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /register_student <id> <name> [tutor_id]")
        return
    ok, err = db.register_student(args[0], args[1], args[2] if len(args) > 2 else None)
    await update.message.reply_text(
        f"✅ Student {args[0]} ({args[1]}) registered." if ok else f"❌ {err}"
    )


@admin_command
async def register_parent_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /register_parent <id> <name> [student_id]")
        return
    ok, err = db.register_parent(args[0], args[1], args[2] if len(args) > 2 else None)
    await update.message.reply_text(
        f"✅ Parent {args[0]} ({args[1]}) registered." if ok else f"❌ {err}"
    )


@admin_command
async def register_tutor_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /register_tutor <id> <name> [subject]")
        return
    db.register_tutor(args[0], args[1], args[2] if len(args) > 2 else None)
    await update.message.reply_text(
        f"✅ Tutor {args[0]} ({args[1]}) registered — pending approval.\n"
        f"Approve with /approve_tutor {args[0]}"
    )


@admin_command
async def approve_tutor_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /approve_tutor <tutor_id>")
        return
    ok = db.approve_tutor(context.args[0])
    await update.message.reply_text("✅ Approved." if ok else "❌ Tutor not found.")


@admin_command
async def assign_tutor_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /assign_tutor <tutor_id> <student_id> [subject]")
        return
    ok, err = db.assign_tutor(args[0], args[1], args[2] if len(args) > 2 else None)
    await update.message.reply_text("✅ Assigned." if ok else f"❌ {err}")


@admin_command
async def link_child_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /link_child <parent_id> <student_id>")
        return
    ok, err = db.link_parent_child(args[0], args[1])
    await update.message.reply_text("✅ Linked." if ok else f"❌ {err}")


@admin_command
async def set_status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            f"Usage: /set_status <student_id> <{'|'.join(db.VALID_STUDENT_STATUSES)}>"
        )
        return
    ok, err = db.set_student_status(args[0], args[1].lower())
    await update.message.reply_text("✅ Updated." if ok else f"❌ {err}")


@admin_command
async def add_admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].lstrip("-").isdigit():
        await update.message.reply_text("Usage: /add_admin <numeric_telegram_id>")
        return
    db.add_admin(int(context.args[0]), " ".join(context.args[1:]) or None)
    await update.message.reply_text(f"✅ {context.args[0]} is now an admin.")


@admin_command
async def pending_payments_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.get_pending_payments()
    if not rows:
        await update.message.reply_text("✅ No pending payments.")
        return
    await update.message.reply_text(
        "🕒 <b>Pending</b>\n\n" + "\n".join(format_payment(p) for p in rows),
        parse_mode=ParseMode.HTML,
    )


@admin_command
async def all_payments_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.get_all_payments()
    if not rows:
        await update.message.reply_text("No payments yet.")
        return
    await update.message.reply_text(
        "💵 <b>All payments</b>\n\n" + "\n".join(format_payment(p) for p in rows),
        parse_mode=ParseMode.HTML,
    )


async def _decide(update, context, status):
    if not context.args or not context.args[0].isdigit():
        verb = "approve" if status == "approved" else "reject"
        await update.message.reply_text(f"Usage: /{verb}_payment <payment_id>")
        return
    ok, err = db.set_payment_status(
        int(context.args[0]), status, update.effective_user.id
    )
    await update.message.reply_text(f"✅ Payment {status}." if ok else f"❌ {err}")


@admin_command
async def approve_payment_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _decide(update, context, "approved")


@admin_command
async def reject_payment_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _decide(update, context, "rejected")


# ---------------------------------------------------------------------
# Fallbacks and error handling
# ---------------------------------------------------------------------

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.effective_message.reply_text(
        "🚪 Session ended. Send /start to begin again."
    )
    return ConversationHandler.END


async def unexpected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Catch anything that doesn't fit the current state without losing it."""
    await update.effective_message.reply_text(
        "❓ I didn't understand that. Use the buttons above, "
        "or send /cancel to start over."
    )
    return None  # stay in the current state


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Unhandled exception", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        message = ("⚠️ Something went wrong on our side. Please try again, "
                   "or send /start to restart.")
        if isinstance(context.error, db.DatabaseError):
            message = "⚠️ The database is unavailable right now. Please try again shortly."
        try:
            await update.effective_message.reply_text(message)
        except Exception:
            pass


# ---------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------

def build_app():
    db.init_db()
    db.seed_admins(require_admins())

    app = ApplicationBuilder().token(require_token()).build()

    text = filters.TEXT & ~filters.COMMAND
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ROLE: [CallbackQueryHandler(choose_role, pattern=r"^role_")],
            STUDENT_ID: [MessageHandler(text, student_id_entered)],
            PARENT_ID: [MessageHandler(text, parent_id_entered)],
            TUTOR_ID: [MessageHandler(text, tutor_id_entered)],
            MENU: [
                CallbackQueryHandler(approve_tutor_button, pattern=r"^tap_"),
                CallbackQueryHandler(menu_action, pattern=r"^(s_|p_|t_|a_|pay_start|logout)"),
            ],
            GRADE_STUDENT: [CallbackQueryHandler(tutor_grade_student, pattern=r"^gs_")],
            GRADE_SUBJECT: [MessageHandler(text, tutor_grade_subject)],
            GRADE_SCORE: [MessageHandler(text, tutor_grade_score)],
            TOPIC_STUDENT: [CallbackQueryHandler(tutor_topic_student, pattern=r"^ts_")],
            TOPIC_TEXT: [MessageHandler(text, tutor_topic_text)],
            TOPIC_DATE: [MessageHandler(text, tutor_topic_date)],
            PAY_CHILD: [CallbackQueryHandler(pay_child, pattern=r"^pc_")],
            PAY_AMOUNT: [MessageHandler(text, pay_amount)],
            PAY_RECEIPT: [MessageHandler(filters.PHOTO | filters.Document.ALL, pay_receipt)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", start),
            MessageHandler(filters.ALL, unexpected),
        ],
        allow_reentry=True,
    )
    app.add_handler(conv)

    # Payment review works from any state, including for admins not in a conversation.
    app.add_handler(CallbackQueryHandler(review_payment, pattern=r"^rev_"))

    for name, handler in [
        ("help", help_cmd), ("myid", myid_cmd), ("admin", admin_help_cmd),
        ("register_student", register_student_cmd),
        ("register_parent", register_parent_cmd),
        ("register_tutor", register_tutor_cmd),
        ("approve_tutor", approve_tutor_cmd),
        ("assign_tutor", assign_tutor_cmd),
        ("link_child", link_child_cmd),
        ("set_status", set_status_cmd),
        ("add_admin", add_admin_cmd),
        ("pending_payments", pending_payments_cmd),
        ("all_payments", all_payments_cmd),
        ("approve_payment", approve_payment_cmd),
        ("reject_payment", reject_payment_cmd),
    ]:
        app.add_handler(CommandHandler(name, handler))

    app.add_error_handler(on_error)
    return app


def main():
    logger.info("Starting Wave Academy bot")
    build_app().run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
