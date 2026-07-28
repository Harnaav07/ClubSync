# ==========================================
# ClubSync Database Setup
# Creates all database tables and inserts
# the default user accounts and statistics.
# ==========================================


# ==========================================
# Import required libraries
# ==========================================

import sqlite3

from werkzeug.security import generate_password_hash


# ==========================================
# Connect to the SQLite database
# ==========================================

connection = sqlite3.connect("clubsync.db")

# Enable foreign-key relationships in SQLite
connection.execute("PRAGMA foreign_keys = ON")

# Create a cursor used to execute SQL commands
cursor = connection.cursor()


# ==========================================
# Users Table
# Stores login and role information.
# ==========================================

cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL
    )
""")


# ==========================================
# Default User Accounts
# Passwords are securely hashed before
# being stored in the database.
# ==========================================

users = [
    (
        "Admin User",
        "admin@clubsync.com",
        generate_password_hash("admin123"),
        "Admin"
    ),
    (
        "Coach User",
        "coach@clubsync.com",
        generate_password_hash("coach123"),
        "Coach"
    ),
    (
        "Viewer User",
        "viewer@clubsync.com",
        generate_password_hash("viewer123"),
        "Viewer"
    )
]


# Insert each default account.
# Existing accounts are skipped because
# email addresses must be unique.
for user in users:
    try:
        cursor.execute("""
            INSERT INTO users (
                name,
                email,
                password_hash,
                role
            )
            VALUES (?, ?, ?, ?)
        """, user)

    except sqlite3.IntegrityError:
        pass


# ==========================================
# Dashboard Statistics Table
# Stores summary values displayed on the
# ClubSync dashboard.
# ==========================================

cursor.execute("""
    CREATE TABLE IF NOT EXISTS dashboard_stats (
        stat_id INTEGER PRIMARY KEY AUTOINCREMENT,
        total_players INTEGER NOT NULL,
        attendance_records INTEGER NOT NULL,
        overdue_fees INTEGER NOT NULL,
        club_assets INTEGER NOT NULL
    )
""")


# Check whether an initial statistics record
# has already been created.
cursor.execute("""
    SELECT COUNT(*)
    FROM dashboard_stats
""")

if cursor.fetchone()[0] == 0:
    cursor.execute("""
        INSERT INTO dashboard_stats (
            total_players,
            attendance_records,
            overdue_fees,
            club_assets
        )
        VALUES (0, 126, 9, 42)
    """)


# ==========================================
# Players Table
# Stores player, team, contact and
# registration information.
# ==========================================

cursor.execute("""
    CREATE TABLE IF NOT EXISTS players (
        player_id INTEGER PRIMARY KEY AUTOINCREMENT,
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        date_of_birth TEXT NOT NULL,
        age_group TEXT NOT NULL,
        team TEXT NOT NULL,
        position TEXT NOT NULL,
        contact_phone TEXT,
        emergency_contact TEXT,
        medical_notes TEXT,
        registration_status TEXT NOT NULL DEFAULT 'Active'
    )
""")


# ==========================================
# Attendance Table
# Stores one attendance status for each
# player on each attendance date.
# ==========================================

cursor.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        attendance_id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id INTEGER NOT NULL,
        attendance_date TEXT NOT NULL,
        attendance_status TEXT NOT NULL
            CHECK (
                attendance_status IN (
                    'Present',
                    'Absent',
                    'Late'
                )
            ),

        UNIQUE (
            player_id,
            attendance_date
        ),

        FOREIGN KEY (player_id)
            REFERENCES players(player_id)
            ON DELETE CASCADE
    )
""")


# ==========================================
# Save changes and close the database
# ==========================================

connection.commit()
connection.close()

print("ClubSync database tables created successfully.")