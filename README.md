# Wave Academy

Wave Academy is a Telegram-based tutoring management bot for home-to-home
education services. It connects students, parents, tutors, and admins in
one platform: result tracking, tutor management, payment receipt
submission, and academic progress monitoring, all through Telegram.

## Features

- **Students** — view grades, see their next scheduled session, check status
- **Parents** — view their child's grades and status, get their tutor's
  name/subject, submit payment receipts (photo) for admin approval
- **Tutors** — record grades, schedule the next study topic/date, list
  their assigned students
- **Admins** — register students/parents/tutors, review and approve/reject
  payment receipts, all via bot commands

## Project structure

```
wave_academy/
├── bot.py              # Telegram handlers and conversation flow
├── db.py                # SQLite schema and data access functions
├── config.py             # Loads BOT_TOKEN / admin IDs from environment
├── requirements.txt
├── .env.example
└── .gitignore
```

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.

3. Copy `.env.example` to `.env` and fill in your token and admin Telegram
   IDs (message [@userinfobot](https://t.me/userinfobot) to find your own
   numeric ID):
   ```bash
   cp .env.example .env
   ```

4. Run the bot:
   ```bash
   python bot.py
   ```

The database (`wave_academy.db`) and its tables are created automatically
on first run.

## Admin commands

Only Telegram accounts listed in `ADMIN_TELEGRAM_IDS` can use these:

| Command | Usage |
|---|---|
| Register a student | `/register_student <student_id> <name> [tutor_id]` |
| Register a parent | `/register_parent <parent_id> <name> <child_student_id>` |
| Register a tutor | `/register_tutor <tutor_id> <name> <subject>` |
| Change student status | `/set_status <student_id> <status>` |
| List pending payments | `/pending_payments` |
| Approve a payment | `/approve_payment <payment_id>` |
| Reject a payment | `/reject_payment <payment_id>` |

A person must be registered by an admin **before** they can log in through
the bot's Student/Parent/Tutor menu — the first message with their ID
links their Telegram account to that record.

<<<<<<< HEAD
=======

>>>>>>> main
