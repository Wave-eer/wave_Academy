# Wave Academy

Wave Academy is a Telegram-based tutoring management bot for home-to-home
education services. It connects students, parents, tutors, and admins in
one platform: result tracking, tutor management, payment receipt
submission, and academic progress monitoring, all through Telegram.

## Features

- **Students** — view grades, see their next scheduled session, check
  enrollment status and average, submit payment receipts
- **Parents** — view each child's grades and performance breakdown, get
  their tutor's name/subject/phone, submit payment receipts for approval
- **Tutors** — record grades, schedule the next study topic and date
  (students and parents are notified automatically), list their students.
  A tutor cannot log in until an admin approves the account
- **Admins** — register students/parents/tutors, approve tutors, assign
  tutors to students, link parents to children, change enrollment status,
  and approve/reject payment receipts with inline buttons

Everything runs through inline keyboards inside a single
`ConversationHandler`, so an unexpected message never strands a user
mid-flow.

## Project structure

```
wave_academy/
├── bot.py                  # Telegram handlers and conversation flow
├── db.py                   # SQLite schema, migrations, data access
├── config.py               # Loads BOT_TOKEN / admin IDs from environment
├── seed.py                 # Sample data for local testing
├── tests/
│   └── test_wave_academy.py  # Offline test suite (no bot token needed)
├── requirements.txt
├── .env.example
└── .gitignore
```

## Setup

1. Install dependencies (Python 3.9+):
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

4. Optionally load sample students, tutors, and parents:
   ```bash
   python seed.py            # safe to re-run
   python seed.py --reset    # wipe the database first
   ```

5. Run the bot:
   ```bash
   python bot.py
   ```

The database (`wave_academy.db`) and its tables are created automatically
on first run, and existing databases are migrated in place.

## Tests

The suite runs entirely offline against a temporary database — no bot
token or network access required:

```bash
python tests/test_wave_academy.py
```

## Admin commands

Only Telegram accounts listed in `ADMIN_TELEGRAM_IDS` (or added later with
`/add_admin`) can use these. Admins skip the login step — their Telegram
ID is the credential.

| Command | Purpose |
|---|---|
| `/register_student <id> <name> [tutor_id]` | Create or rename a student |
| `/register_parent <id> <name> [student_id]` | Create a parent, optionally linked to a child |
| `/register_tutor <id> <name> [subject]` | Create a tutor (starts unapproved) |
| `/approve_tutor <tutor_id>` | Let a tutor log in |
| `/assign_tutor <tutor_id> <student_id> [subject]` | Assign a tutor to a student |
| `/link_child <parent_id> <student_id>` | Link a parent to another child |
| `/set_status <student_id> <status>` | `active`, `inactive`, `suspended`, or `graduated` |
| `/add_admin <telegram_id> [name]` | Grant admin rights |
| `/pending_payments` · `/all_payments` | List receipts |
| `/approve_payment <id>` · `/reject_payment <id>` | Decide a receipt |
| `/admin` | Show this list inside Telegram |
| `/myid` | Show your numeric Telegram ID |

A person must be registered by an admin **before** they can log in through
the bot's Student/Parent/Tutor menu — the first message with their ID
links their Telegram account to that record. An ID already linked to
someone else is refused, so accounts cannot be hijacked.

## Notes on data

- A parent may have several children; a student may have a different tutor
  per subject. Both are stored in junction tables with real foreign keys.
- Tutors can only record grades and sessions for students actually
  assigned to them; the check is repeated at submit time, not just when
  the menu is drawn.
- A payment can only be decided once, so two admins cannot both approve
  the same receipt.
- `wave_academy.db` and `.env` are gitignored — never commit them.
