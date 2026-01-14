import sqlite3

conn = sqlite3.connect("wave_academy.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS students (
    student_id TEXT PRIMARY KEY,
    name TEXT,
    status TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS results (
    student_id TEXT,
    subject TEXT,
    score INTEGER
)
""")

conn.commit()
conn.close()

print("✅ Database created successfully")
