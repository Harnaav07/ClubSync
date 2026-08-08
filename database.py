import sqlite3

from werkzeug.security import generate_password_hash


# Connect to the SQLite database

connection = sqlite3.connect("clubsync.db")

# Enable foreign-key relationships in SQLite

connection.execute("PRAGMA foreign_keys = ON")

# Create a cursor used to execute SQL commands

cursor = connection.cursor()


# =========================================================
# Users Table
# =========================================================
# Stores login and role information.

cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL
            CHECK (
                role IN (
                    'Admin',
                    'Coach',
                    'Viewer'
                )
            )
    )
""")


# =========================================================
# Default User Accounts
# =========================================================
# Passwords are securely hashed before
# being stored in the database.

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


# =========================================================
# Dashboard Statistics Table
# =========================================================
# Stores summary values displayed on the
# ClubSync dashboard.

cursor.execute("""
    CREATE TABLE IF NOT EXISTS dashboard_stats (
        stat_id INTEGER PRIMARY KEY AUTOINCREMENT,
        total_players INTEGER NOT NULL DEFAULT 0,
        attendance_records INTEGER NOT NULL DEFAULT 0,
        overdue_fees INTEGER NOT NULL DEFAULT 0,
        club_assets INTEGER NOT NULL DEFAULT 0
    )
""")


# Add the first dashboard statistics record
# only when the table is empty.

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
        VALUES (0, 126, 9, 0)
    """)


# =========================================================
# Players Table
# =========================================================
# Stores player, team, contact and
# registration information.

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
        registration_status TEXT NOT NULL
            DEFAULT 'Active'
            CHECK (
                registration_status IN (
                    'Active',
                    'Inactive'
                )
            )
    )
""")


# =========================================================
# Attendance Table
# =========================================================
# Stores one attendance status for each
# player on each attendance date.

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

        attendance_note TEXT,
        coach_name TEXT,

        UNIQUE (
            player_id,
            attendance_date
        ),

        FOREIGN KEY (player_id)
            REFERENCES players(player_id)
            ON DELETE CASCADE
    )
""")


# Add newer attendance fields to an older
# copy of the database when needed.

cursor.execute(
    "PRAGMA table_info(attendance)"
)

attendance_columns = {
    column[1]
    for column in cursor.fetchall()
}


if "attendance_note" not in attendance_columns:

    cursor.execute("""
        ALTER TABLE attendance
        ADD COLUMN attendance_note TEXT
    """)


if "coach_name" not in attendance_columns:

    cursor.execute("""
        ALTER TABLE attendance
        ADD COLUMN coach_name TEXT
    """)


# =========================================================
# Team Line-ups Table
# =========================================================
# Stores each selected player and pitch
# position for an age group and formation.

cursor.execute("""
    CREATE TABLE IF NOT EXISTS team_lineups (
        lineup_id INTEGER PRIMARY KEY AUTOINCREMENT,

        age_group TEXT NOT NULL,

        formation TEXT NOT NULL
            CHECK (
                formation IN (
                    '4-3-3',
                    '4-4-2',
                    '3-5-2'
                )
            ),

        slot_name TEXT NOT NULL,

        player_id INTEGER NOT NULL,

        saved_by_user_id INTEGER,

        updated_at TEXT NOT NULL
            DEFAULT CURRENT_TIMESTAMP,

        UNIQUE (
            age_group,
            formation,
            slot_name
        ),

        UNIQUE (
            age_group,
            formation,
            player_id
        ),

        FOREIGN KEY (player_id)
            REFERENCES players(player_id)
            ON DELETE CASCADE,

        FOREIGN KEY (saved_by_user_id)
            REFERENCES users(user_id)
            ON DELETE SET NULL
    )
""")


# =========================================================
# Fees Table
# =========================================================
# Stores one fee record for each player
# during each season.

cursor.execute("""
    CREATE TABLE IF NOT EXISTS fees (
        fee_id INTEGER PRIMARY KEY AUTOINCREMENT,

        player_id INTEGER NOT NULL,

        season INTEGER NOT NULL,

        amount_due REAL NOT NULL
            DEFAULT 0
            CHECK (
                amount_due >= 0
            ),

        amount_paid REAL NOT NULL
            DEFAULT 0
            CHECK (
                amount_paid >= 0
            ),

        payment_status TEXT NOT NULL
            DEFAULT 'Unpaid'
            CHECK (
                payment_status IN (
                    'Paid',
                    'Part Payment',
                    'Overdue',
                    'Unpaid'
                )
            ),

        due_date TEXT,

        payment_date TEXT,

        notes TEXT,

        created_at TEXT NOT NULL
            DEFAULT CURRENT_TIMESTAMP,

        updated_at TEXT NOT NULL
            DEFAULT CURRENT_TIMESTAMP,

        UNIQUE (
            player_id,
            season
        ),

        FOREIGN KEY (player_id)
            REFERENCES players(player_id)
            ON DELETE CASCADE
    )
""")


# Add newer fee fields to an older copy
# of the database when needed.

cursor.execute(
    "PRAGMA table_info(fees)"
)

fee_columns = {
    column[1]
    for column in cursor.fetchall()
}


if "season" not in fee_columns:

    cursor.execute("""
        ALTER TABLE fees
        ADD COLUMN season INTEGER
        NOT NULL DEFAULT 2026
    """)


if "amount_due" not in fee_columns:

    cursor.execute("""
        ALTER TABLE fees
        ADD COLUMN amount_due REAL
        NOT NULL DEFAULT 0
    """)


if "amount_paid" not in fee_columns:

    cursor.execute("""
        ALTER TABLE fees
        ADD COLUMN amount_paid REAL
        NOT NULL DEFAULT 0
    """)


if "payment_status" not in fee_columns:

    cursor.execute("""
        ALTER TABLE fees
        ADD COLUMN payment_status TEXT
        NOT NULL DEFAULT 'Unpaid'
    """)


if "due_date" not in fee_columns:

    cursor.execute("""
        ALTER TABLE fees
        ADD COLUMN due_date TEXT
    """)


if "payment_date" not in fee_columns:

    cursor.execute("""
        ALTER TABLE fees
        ADD COLUMN payment_date TEXT
    """)


if "notes" not in fee_columns:

    cursor.execute("""
        ALTER TABLE fees
        ADD COLUMN notes TEXT
    """)


if "created_at" not in fee_columns:

    cursor.execute("""
        ALTER TABLE fees
        ADD COLUMN created_at TEXT
    """)

    cursor.execute("""
        UPDATE fees
        SET created_at = CURRENT_TIMESTAMP
        WHERE created_at IS NULL
    """)


if "updated_at" not in fee_columns:

    cursor.execute("""
        ALTER TABLE fees
        ADD COLUMN updated_at TEXT
    """)

    cursor.execute("""
        UPDATE fees
        SET updated_at = CURRENT_TIMESTAMP
        WHERE updated_at IS NULL
    """)


# =========================================================
# Assets Table
# =========================================================
# Stores equipment and club asset information.

cursor.execute("""
    CREATE TABLE IF NOT EXISTS assets (
        asset_id INTEGER PRIMARY KEY AUTOINCREMENT,

        name TEXT NOT NULL,

        category TEXT NOT NULL,

        condition TEXT NOT NULL
            CHECK (
                condition IN (
                    'Good',
                    'Needs Review',
                    'Damaged'
                )
            ),

        availability TEXT NOT NULL
            CHECK (
                availability IN (
                    'Available',
                    'In use',
                    'Unavailable'
                )
            ),

        allocated_to TEXT,

        created_at TEXT NOT NULL
            DEFAULT CURRENT_TIMESTAMP,

        updated_at TEXT NOT NULL
            DEFAULT CURRENT_TIMESTAMP
    )
""")


# =========================================================
# Assets Table Compatibility
# =========================================================
# Allows an older copy of clubsync.db to
# receive newer asset fields if required.

cursor.execute(
    "PRAGMA table_info(assets)"
)

asset_columns = {
    column[1]
    for column in cursor.fetchall()
}


if "allocated_to" not in asset_columns:

    cursor.execute("""
        ALTER TABLE assets
        ADD COLUMN allocated_to TEXT
    """)


if "created_at" not in asset_columns:

    cursor.execute("""
        ALTER TABLE assets
        ADD COLUMN created_at TEXT
    """)

    cursor.execute("""
        UPDATE assets
        SET created_at = CURRENT_TIMESTAMP
        WHERE created_at IS NULL
    """)


if "updated_at" not in asset_columns:

    cursor.execute("""
        ALTER TABLE assets
        ADD COLUMN updated_at TEXT
    """)

    cursor.execute("""
        UPDATE assets
        SET updated_at = CURRENT_TIMESTAMP
        WHERE updated_at IS NULL
    """)


# =========================================================
# Dashboard Asset Count
# =========================================================
# Keep the dashboard Club Assets summary
# linked to the actual Assets table.

cursor.execute("""
    SELECT COUNT(*)
    FROM assets
""")

asset_count = cursor.fetchone()[0]


cursor.execute("""
    UPDATE dashboard_stats
    SET club_assets = ?
    WHERE stat_id = 1
""", (
    asset_count,
))


# =========================================================
# Database Indexes
# =========================================================
# Improve searching and filtering performance.


# Players

cursor.execute("""
    CREATE INDEX IF NOT EXISTS
    index_players_age_group

    ON players(age_group)
""")


# Attendance

cursor.execute("""
    CREATE INDEX IF NOT EXISTS
    index_attendance_date

    ON attendance(attendance_date)
""")


# Teams

cursor.execute("""
    CREATE INDEX IF NOT EXISTS
    index_team_lineups

    ON team_lineups(
        age_group,
        formation
    )
""")


# Fees

cursor.execute("""
    CREATE INDEX IF NOT EXISTS
    index_fees_season

    ON fees(season)
""")


cursor.execute("""
    CREATE INDEX IF NOT EXISTS
    index_fees_status

    ON fees(payment_status)
""")


cursor.execute("""
    CREATE INDEX IF NOT EXISTS
    index_fees_player

    ON fees(player_id)
""")


# Assets

cursor.execute("""
    CREATE INDEX IF NOT EXISTS
    index_assets_name

    ON assets(name)
""")


cursor.execute("""
    CREATE INDEX IF NOT EXISTS
    index_assets_category

    ON assets(category)
""")


cursor.execute("""
    CREATE INDEX IF NOT EXISTS
    index_assets_condition

    ON assets(condition)
""")


cursor.execute("""
    CREATE INDEX IF NOT EXISTS
    index_assets_availability

    ON assets(availability)
""")


# =========================================================
# Save Changes
# =========================================================

connection.commit()

connection.close()


print(
    "ClubSync database tables created successfully."
)