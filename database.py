import sqlite3
from werkzeug.security import generate_password_hash

connection = sqlite3.connect("clubsync.db")
cursor = connection.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL
)
""")

users = [
    ("Admin User", "admin@clubsync.com", generate_password_hash("admin123"), "Admin"),
    ("Coach User", "coach@clubsync.com", generate_password_hash("coach123"), "Coach"),
    ("Viewer User", "viewer@clubsync.com", generate_password_hash("viewer123"), "Viewer")
]

for user in users:
    try:
        cursor.execute("""
        INSERT INTO users (name, email, password_hash, role)
        VALUES (?, ?, ?, ?)
        """, user)
    except sqlite3.IntegrityError:
        pass

cursor.execute("""
CREATE TABLE IF NOT EXISTS dashboard_stats (
    stat_id INTEGER PRIMARY KEY AUTOINCREMENT,
    total_players INTEGER NOT NULL,
    attendance_records INTEGER NOT NULL,
    overdue_fees INTEGER NOT NULL,
    club_assets INTEGER NOT NULL
)
""")

cursor.execute("SELECT COUNT(*) FROM dashboard_stats")
if cursor.fetchone()[0] == 0:
    cursor.execute("""
    INSERT INTO dashboard_stats 
    (total_players, attendance_records, overdue_fees, club_assets)
    VALUES (84, 126, 9, 42)
    """)

connection.commit()
connection.close()

print("Database tables created successfully.")