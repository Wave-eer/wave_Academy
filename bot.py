from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = "7825222032:AAEUtsVwBRDGGv4wnHwLLmf2V1NJyChcgVc"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 Welcome to Wave Academy Bot!\n\n"
        "Who are you?\n"
        "1️⃣ Student\n"
        "2️⃣ Parent\n"
        "3️⃣ Tutor\n\n"
        "Reply with 1, 2, or 3."
    )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    role = context.user_data.get("role")

    # STEP 1: role selection
    if role is None:
        if text == "1":
            context.user_data["role"] = "student"
            await update.message.reply_text("🎓 Student selected.\nEnter your Student ID:")
        elif text == "2":
            context.user_data["role"] = "parent"
            await update.message.reply_text("👨‍👩‍👧 Parent selected.\nEnter your Parent ID:")
        elif text == "3":
            context.user_data["role"] = "tutor"
            await update.message.reply_text("👨‍🏫 Tutor selected.\nEnter your Tutor ID:")
        else:
            await update.message.reply_text("❗ Please reply with 1, 2, or 3.")
        return

    # STEP 2: ID handling
    if role == "student":
        context.user_data["student_id"] = text
        await update.message.reply_text(
            f"✅ Student ID saved: {text}\n\n"
            "Menu:\n"
            "1️⃣ View Results\n"
            "2️⃣ Next Study Session\n"
            "3️⃣ My Status"
        )

    elif role == "parent":
        context.user_data["parent_id"] = text
        await update.message.reply_text(
            f"✅ Parent ID saved: {text}\n\n"
            "Menu:\n"
            "1️⃣ Child Grades\n"
            "2️⃣ Performance Status\n"
            "3️⃣ Contact Teacher"
        )

    elif role == "tutor":
        context.user_data["tutor_id"] = text
        await update.message.reply_text(
            f"✅ Tutor ID saved: {text}\n\n"
            "Menu:\n"
            "1️⃣ Enter Grades\n"
            "2️⃣ Update Study Topics\n"
            "3️⃣ View Students"
        )


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # handlers FIRST
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    # run LAST
    app.run_polling()


if __name__ == "__main__":
    main()
