"""
Wave Academy Telegram bot.

Roles:
    Student -> view results, next session, status
    Parent  -> child's grades, performance status, contact teacher, submit payment receipt
    Tutor   -> enter grades, update study topics, view assigned students
    Admin   -> registers people and reviews payments via commands (not the numbered menu)

Run:
    python bot.py
"""

import logging

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import db
from config import BOT_TOKEN, ADMIN_TELEGRAM_IDS

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------
# Conversation states
# ---------------------------------------------------------------------
(
    ROLE,
    STUDENT_ID, PARENT_ID, TUTOR_ID,
    STUDENT_MENU, PARENT_MENU, TUTOR_MENU,
    TUTOR_GRADE_STUDENT, TUTOR_GRADE_SUBJECT, TUTOR_GRADE_SCORE,
    TUTOR_TOPIC_STUDENT, TUTOR_TOPIC_TEXT, TUTOR_TOPIC_DATE,
    PARENT_RECEIPT_AMOUNT, PARENT_RECEIPT_PHOTO,
) = range(15)


def is_admin(update: Update) -> bool:
    return update.effective_user.id in ADMIN_TELEGRAM_IDS


# ---------------------------------------------------------------------
# Entry point / role selection
# ---------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 Welcome to Wave Academy Bot!\n\n"
        "Who are you?\n"
        "1️⃣ Student\n"
        "2️⃣ Parent\n"
        "3️⃣ Tutor\n\n"
        "Reply with 1, 2, or 3. Send /cancel any time to start over."
    )
    return ROLE


async def choose_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "1":
        await update.message.reply_text("🎓 Student selected.\nEnter your Student ID:")
        return STUDENT_ID
    elif text == "2":
        await update.message.reply_text("👨‍👩‍👧 Parent selected.\nEnter your Parent ID:")
        return PARENT_ID
    elif text == "3":
        await update.message.reply_text("👨‍🏫 Tutor selected.\nEnter your Tutor ID:")
        return TUTOR_ID
    else:
        await update.message.reply_text("❗ Please reply with 1, 2, or 3.")
        return ROLE


STUDENT_MENU_TEXT = (
    "Menu:\n"
    "1️⃣ View Results\n"
    "2️⃣ Next Study Session\n"
    "3️⃣ My Status\n\n"
    "Send /cancel to log out."
)
PARENT_MENU_TEXT = (
    "Menu:\n"
    "1️⃣ Child Grades\n"
    "2️⃣ Performance Status\n"
    "3️⃣ Contact Teacher\n"
    "4️⃣ Submit Payment Receipt\n\n"
    "Send /cancel to log out."
)
TUTOR_MENU_TEXT = (
    "Menu:\n"
    "1️⃣ Enter Grades\n"
    "2️⃣ Update Study Topics\n"
    "3️⃣ View Students\n\n"
    "Send /cancel to log out."
)


# ---------------------------------------------------------------------
# Student
# ---------------------------------------------------------------------

async def student_id_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    student_id = update.message.text.strip()
    row = db.link_student(student_id, update.effective_user.id)
    if row is None:
        await update.message.reply_text(
            "❌ Student ID not found. Ask your admin to register you, "
            "or send /cancel to try a different role."
        )
        return STUDENT_ID

    context.user_data["student_id"] = student_id
    await update.message.reply_text(f"✅ Welcome, {row['name']}!\n\n{STUDENT_MENU_TEXT}")
    return STUDENT_MENU


async def student_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.strip()
    student_id = context.user_data["student_id"]

    if choice == "1":
        rows = db.get_results(student_id)
        if not rows:
            await update.message.reply_text("No results recorded yet.")
        else:
            lines = [f"• {r['subject']}: {r['score']} ({r['recorded_at']})" for r in rows]
            await update.message.reply_text("📊 Your results:\n" + "\n".join(lines))

    elif choice == "2":
        session = db.get_next_session(student_id)
        if session is None:
            await update.message.reply_text("No upcoming study session scheduled yet.")
        else:
            await update.message.reply_text(
                f"📅 Next session: {session['session_date']}\nTopic: {session['topic']}"
            )

    elif choice == "3":
        student = db.get_student(student_id)
        await update.message.reply_text(f"ℹ️ Status: {student['status']}")

    else:
        await update.message.reply_text("❗ Please reply with 1, 2, or 3.")
        return STUDENT_MENU

    await update.message.reply_text(STUDENT_MENU_TEXT)
    return STUDENT_MENU


# ---------------------------------------------------------------------
# Parent
# ---------------------------------------------------------------------

async def parent_id_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parent_id = update.message.text.strip()
    row = db.link_parent(parent_id, update.effective_user.id)
    if row is None:
        await update.message.reply_text(
            "❌ Parent ID not found. Ask your admin to register you, "
            "or send /cancel to try a different role."
        )
        return PARENT_ID

    context.user_data["parent_id"] = parent_id
    context.user_data["child_student_id"] = row["child_student_id"]
    await update.message.reply_text(f"✅ Welcome, {row['name']}!\n\n{PARENT_MENU_TEXT}")
    return PARENT_MENU


async def parent_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.strip()
    child_id = context.user_data.get("child_student_id")

    if choice == "1":
        if not child_id:
            await update.message.reply_text("No child linked to your account yet.")
        else:
            rows = db.get_results(child_id)
            if not rows:
                await update.message.reply_text("No results recorded for your child yet.")
            else:
                lines = [f"• {r['subject']}: {r['score']} ({r['recorded_at']})" for r in rows]
                await update.message.reply_text("📊 Child's results:\n" + "\n".join(lines))

    elif choice == "2":
        if not child_id:
            await update.message.reply_text("No child linked to your account yet.")
        else:
            student = db.get_student(child_id)
            await update.message.reply_text(f"ℹ️ Status: {student['status']}")

    elif choice == "3":
        if not child_id:
            await update.message.reply_text("No child linked to your account yet.")
        else:
            tutor = db.get_tutor_for_student(child_id)
            if tutor is None:
                await update.message.reply_text("No tutor assigned yet.")
            else:
                await update.message.reply_text(
                    f"👨‍🏫 {tutor['name']} ({tutor['subject']})\n"
                    "Ask an admin to share direct contact details."
                )

    elif choice == "4":
        await update.message.reply_text("💵 Enter the amount paid (e.g. 500 ETB):")
        return PARENT_RECEIPT_AMOUNT

    else:
        await update.message.reply_text("❗ Please reply with 1, 2, 3, or 4.")
        return PARENT_MENU

    await update.message.reply_text(PARENT_MENU_TEXT)
    return PARENT_MENU


async def parent_receipt_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["receipt_amount"] = update.message.text.strip()
    await update.message.reply_text("📎 Now send a photo of the payment receipt.")
    return PARENT_RECEIPT_PHOTO


async def parent_receipt_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("Please send the receipt as a photo.")
        return PARENT_RECEIPT_PHOTO

    file_id = update.message.photo[-1].file_id
    parent_id = context.user_data["parent_id"]
    child_id = context.user_data.get("child_student_id")
    amount = context.user_data.get("receipt_amount")

    payment_id = db.submit_payment(parent_id, child_id, amount, file_id)

    await update.message.reply_text(
        f"✅ Receipt submitted (reference #{payment_id}). An admin will review it."
    )

    for admin_id in ADMIN_TELEGRAM_IDS:
        try:
            await context.bot.send_photo(
                chat_id=admin_id,
                photo=file_id,
                caption=(
                    f"💵 New payment receipt #{payment_id}\n"
                    f"Parent: {parent_id}\nStudent: {child_id}\nAmount: {amount}\n\n"
                    f"Approve: /approve_payment {payment_id}\n"
                    f"Reject: /reject_payment {payment_id}"
                ),
            )
        except Exception:
            logger.exception("Failed to notify admin %s", admin_id)

    await update.message.reply_text(PARENT_MENU_TEXT)
    return PARENT_MENU


# ---------------------------------------------------------------------
# Tutor
# ---------------------------------------------------------------------

async def tutor_id_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tutor_id = update.message.text.strip()
    row = db.link_tutor(tutor_id, update.effective_user.id)
    if row is None:
        await update.message.reply_text(
            "❌ Tutor ID not found. Ask your admin to register you, "
            "or send /cancel to try a different role."
        )
        return TUTOR_ID

    context.user_data["tutor_id"] = tutor_id
    await update.message.reply_text(f"✅ Welcome, {row['name']}!\n\n{TUTOR_MENU_TEXT}")
    return TUTOR_MENU


async def tutor_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.strip()

    if choice == "1":
        await update.message.reply_text("Enter the Student ID to grade:")
        return TUTOR_GRADE_STUDENT

    elif choice == "2":
        await update.message.reply_text("Enter the Student ID for the study session:")
        return TUTOR_TOPIC_STUDENT

    elif choice == "3":
        rows = db.get_students_for_tutor(context.user_data["tutor_id"])
        if not rows:
            await update.message.reply_text("No students assigned to you yet.")
        else:
            lines = [f"• {r['student_id']} — {r['name']} ({r['status']})" for r in rows]
            await update.message.reply_text("👥 Your students:\n" + "\n".join(lines))

    else:
        await update.message.reply_text("❗ Please reply with 1, 2, or 3.")
        return TUTOR_MENU

    await update.message.reply_text(TUTOR_MENU_TEXT)
    return TUTOR_MENU


async def tutor_grade_student(update: Update, context: ContextTypes.DEFAULT_TYPE):
    student_id = update.message.text.strip()
    if db.get_student(student_id) is None:
        await update.message.reply_text("❌ Unknown Student ID. Try again, or /cancel.")
        return TUTOR_GRADE_STUDENT
    context.user_data["grade_student_id"] = student_id
    await update.message.reply_text("Enter the subject:")
    return TUTOR_GRADE_SUBJECT


async def tutor_grade_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["grade_subject"] = update.message.text.strip()
    await update.message.reply_text("Enter the score (number):")
    return TUTOR_GRADE_SCORE


async def tutor_grade_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.lstrip("-").isdigit():
        await update.message.reply_text("Please enter a numeric score.")
        return TUTOR_GRADE_SCORE

    db.add_result(
        context.user_data["grade_student_id"],
        context.user_data["grade_subject"],
        int(text),
        context.user_data["tutor_id"],
    )
    await update.message.reply_text("✅ Grade recorded.\n\n" + TUTOR_MENU_TEXT)
    return TUTOR_MENU


async def tutor_topic_student(update: Update, context: ContextTypes.DEFAULT_TYPE):
    student_id = update.message.text.strip()
    if db.get_student(student_id) is None:
        await update.message.reply_text("❌ Unknown Student ID. Try again, or /cancel.")
        return TUTOR_TOPIC_STUDENT
    context.user_data["topic_student_id"] = student_id
    await update.message.reply_text("Enter the topic for the next session:")
    return TUTOR_TOPIC_TEXT


async def tutor_topic_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["topic_text"] = update.message.text.strip()
    await update.message.reply_text("Enter the session date (e.g. 2026-07-10):")
    return TUTOR_TOPIC_DATE


async def tutor_topic_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.add_session(
        context.user_data["topic_student_id"],
        context.user_data["tutor_id"],
        context.user_data["topic_text"],
        update.message.text.strip(),
    )
    await update.message.reply_text("✅ Study session saved.\n\n" + TUTOR_MENU_TEXT)
    return TUTOR_MENU


# ---------------------------------------------------------------------
# Cancel / fallback
# ---------------------------------------------------------------------

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Session ended. Send /start to begin again.")
    return ConversationHandler.END


# ---------------------------------------------------------------------
# Admin commands (outside the conversation, gated by ADMIN_TELEGRAM_IDS)
# ---------------------------------------------------------------------

async def admin_only_notice(update: Update):
    await update.message.reply_text("⛔ This command is for admins only.")


async def register_student_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return await admin_only_notice(update)
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /register_student <student_id> <name> [tutor_id]"
        )
        return
    student_id, name = args[0], args[1]
    tutor_id = args[2] if len(args) > 2 else None
    db.register_student(student_id, name, tutor_id)
    await update.message.reply_text(f"✅ Student {student_id} ({name}) registered.")


async def register_parent_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return await admin_only_notice(update)
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "Usage: /register_parent <parent_id> <name> <child_student_id>"
        )
        return
    db.register_parent(args[0], args[1], args[2])
    await update.message.reply_text(f"✅ Parent {args[0]} ({args[1]}) registered.")


async def register_tutor_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return await admin_only_notice(update)
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "Usage: /register_tutor <tutor_id> <name> <subject>"
        )
        return
    db.register_tutor(args[0], args[1], args[2])
    await update.message.reply_text(f"✅ Tutor {args[0]} ({args[1]}) registered.")


async def set_status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return await admin_only_notice(update)
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /set_status <student_id> <status>")
        return
    ok = db.set_student_status(args[0], args[1])
    await update.message.reply_text("✅ Updated." if ok else "❌ Student not found.")


async def pending_payments_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return await admin_only_notice(update)
    rows = db.get_pending_payments()
    if not rows:
        await update.message.reply_text("No pending payments.")
        return
    lines = [
        f"#{r['id']} — parent {r['parent_id']}, student {r['student_id']}, "
        f"amount {r['amount']}, submitted {r['submitted_at']}"
        for r in rows
    ]
    await update.message.reply_text("💵 Pending payments:\n" + "\n".join(lines))


async def approve_payment_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return await admin_only_notice(update)
    if not context.args:
        await update.message.reply_text("Usage: /approve_payment <payment_id>")
        return
    ok = db.set_payment_status(int(context.args[0]), "approved")
    await update.message.reply_text("✅ Approved." if ok else "❌ Payment not found.")


async def reject_payment_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return await admin_only_notice(update)
    if not context.args:
        await update.message.reply_text("Usage: /reject_payment <payment_id>")
        return
    ok = db.set_payment_status(int(context.args[0]), "rejected")
    await update.message.reply_text("✅ Rejected." if ok else "❌ Payment not found.")


# ---------------------------------------------------------------------
# App wiring
# ---------------------------------------------------------------------

def main():
    db.init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ROLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_role)],
            STUDENT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, student_id_entered)],
            PARENT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, parent_id_entered)],
            TUTOR_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, tutor_id_entered)],
            STUDENT_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, student_menu)],
            PARENT_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, parent_menu)],
            TUTOR_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, tutor_menu)],
            TUTOR_GRADE_STUDENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, tutor_grade_student)],
            TUTOR_GRADE_SUBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, tutor_grade_subject)],
            TUTOR_GRADE_SCORE: [MessageHandler(filters.TEXT & ~filters.COMMAND, tutor_grade_score)],
            TUTOR_TOPIC_STUDENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, tutor_topic_student)],
            TUTOR_TOPIC_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, tutor_topic_text)],
            TUTOR_TOPIC_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, tutor_topic_date)],
            PARENT_RECEIPT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, parent_receipt_amount)],
            PARENT_RECEIPT_PHOTO: [MessageHandler(filters.PHOTO, parent_receipt_photo)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv)

    # Admin commands work independently of the role conversation.
    app.add_handler(CommandHandler("register_student", register_student_cmd))
    app.add_handler(CommandHandler("register_parent", register_parent_cmd))
    app.add_handler(CommandHandler("register_tutor", register_tutor_cmd))
    app.add_handler(CommandHandler("set_status", set_status_cmd))
    app.add_handler(CommandHandler("pending_payments", pending_payments_cmd))
    app.add_handler(CommandHandler("approve_payment", approve_payment_cmd))
    app.add_handler(CommandHandler("reject_payment", reject_payment_cmd))

    app.run_polling()


if __name__ == "__main__":
    main()