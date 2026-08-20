import os
import sqlite3

from datetime import date, timedelta

import requests

from dotenv import load_dotenv

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session
)

from werkzeug.security import check_password_hash



# Environment Variables

load_dotenv()

FOOTBALL_DATA_API_KEY = os.getenv(
    "FOOTBALL_DATA_API_KEY"
)

# Set up FOOTBALL DATA BASE URL.
FOOTBALL_DATA_BASE_URL = (
    "https://api.football-data.org/v4"
)



# Flask Setup


app = Flask(__name__)

# Session secret key
app.secret_key = "clubsync_secret_key"



# Database Functions


def get_database_connection():
    """Connect to the ClubSync database."""

    # Open the database connection.
    connection = sqlite3.connect("clubsync.db")

    # Access values using the column names
    connection.row_factory = sqlite3.Row

    # Turn on foreign keys
    connection.execute("PRAGMA foreign_keys = ON")

    return connection


def get_user_by_email(email):
    """Find a user by email."""

    # Open the database connection.
    connection = get_database_connection()

    # Get the matching user record.
    user = connection.execute(
        """
        SELECT *
        FROM users
        WHERE email = ?
        """,
        (email,)
    ).fetchone()

    # Close the database connection.
    connection.close()

    # Return the result.
    return user


def get_dashboard_data():
    """Get live dashboard data directly from ClubSync tables."""

    # Open the database connection.
    connection = get_database_connection()

    # Make sure fee statuses are current before dashboard calculations.
    ensure_fees_table(connection)
    refresh_fee_statuses(connection)

    # Make sure the Assets table exists.
    ensure_assets_table(connection)

    stats = connection.execute("""
        SELECT
            (
                SELECT COUNT(*)
                FROM players
            ) AS total_players,

            (
                SELECT COUNT(*)
                FROM attendance
            ) AS attendance_records,

            (
                SELECT COUNT(*)
                FROM fees
                WHERE payment_status = 'Overdue'
            ) AS overdue_fees,

            (
                SELECT COUNT(*)
                FROM assets
            ) AS club_assets
    """).fetchone()

    # Get the five most recent attendance dates.
    attendance_history = connection.execute("""
        SELECT
            attendance_date,

            COUNT(*) AS total_records,

            SUM(
                CASE
                    WHEN attendance_status = 'Present'
                    THEN 1
                    ELSE 0
                END
            ) AS present_count,

            ROUND(
                (
                    SUM(
                        CASE
                            WHEN attendance_status = 'Present'
                            THEN 1
                            ELSE 0
                        END
                    ) * 100.0
                ) / COUNT(*)
            ) AS present_percentage

        FROM attendance

        GROUP BY attendance_date

        ORDER BY attendance_date DESC

        LIMIT 5
    """).fetchall()

    # Reverse so the oldest of the five dates appears first.
    attendance_history = list(
        reversed(attendance_history)
    )

    # Group current overdue fees by player age group.
    overdue_fee_summary = connection.execute("""
        SELECT
            players.age_group,
            COUNT(*) AS overdue_count

        FROM fees

        INNER JOIN players
            ON players.player_id = fees.player_id

        WHERE fees.payment_status = 'Overdue'

        GROUP BY players.age_group

        ORDER BY
            CASE players.age_group
                WHEN 'U10' THEN 1
                WHEN 'U12' THEN 2
                WHEN 'U14' THEN 3
                WHEN 'U16' THEN 4
                WHEN 'U18' THEN 5
                WHEN 'Senior' THEN 6
                ELSE 7
            END,
            players.age_group
    """).fetchall()

    # Save any refreshed fee statuses.
    connection.commit()
    connection.close()

    # Return the result.
    return (
        stats,
        attendance_history,
        overdue_fee_summary
    )


def ensure_fees_table(connection):
    """Create the fees table if it does not exist."""

    # Run the database command.
    connection.execute("""
        CREATE TABLE IF NOT EXISTS fees (
            fee_id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER NOT NULL,
            season INTEGER NOT NULL,
            amount_due REAL NOT NULL
                DEFAULT 0
                CHECK (amount_due >= 0),
            amount_paid REAL NOT NULL
                DEFAULT 0
                CHECK (amount_paid >= 0),
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


def calculate_fee_status(
    amount_due,
    amount_paid,
    due_date
):
    """Calculate the current payment status."""

    # Check this condition before continuing.
    if amount_due > 0 and amount_paid >= amount_due:
        # Return the result.
        return "Paid"

    # Check this condition before continuing.
    if due_date:
        # Validate the value safely.
        try:
            # Set up parsed due date.
            parsed_due_date = date.fromisoformat(due_date)

            # Check this condition before continuing.
            if parsed_due_date < date.today():
                # Return the result.
                return "Overdue"

        except ValueError:
            pass

    # Check this condition before continuing.
    if amount_paid > 0:
        # Return the result.
        return "Part Payment"

    # Return the result.
    return "Unpaid"


def refresh_fee_statuses(connection):
    """Update stored fee statuses using current values."""

    # Run the fee query.
    fee_records = connection.execute("""
        SELECT
            fee_id,
            amount_due,
            amount_paid,
            due_date,
            payment_status
        FROM fees
    """).fetchall()

    # Process each saved record.
    for fee_record in fee_records:
        # Set up current status.
        current_status = calculate_fee_status(
            float(fee_record["amount_due"]),
            float(fee_record["amount_paid"]),
            fee_record["due_date"]
        )

        # Check this condition before continuing.
        if current_status != fee_record["payment_status"]:
            # Run the database command.
            connection.execute("""
                UPDATE fees
                SET payment_status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE fee_id = ?
            """, (
                current_status,
                fee_record["fee_id"]
            ))


def refresh_overdue_fee_dashboard(connection):
    """Update the dashboard overdue-fee count."""

    # Set up overdue count
    overdue_count = connection.execute("""
        SELECT COUNT(*)
        FROM fees
        WHERE payment_status = 'Overdue'
    """).fetchone()[0]

    # Run the database command
    connection.execute("""
        UPDATE dashboard_stats
        SET overdue_fees = ?
        WHERE stat_id = 1
    """, (
        overdue_count,
    ))


# Football-Data.org API

FOOTBALL_COMPETITIONS = {
    "": "All Competitions",
    "PL": "Premier League",
    "CL": "Champions League",
    "PD": "La Liga",
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "FL1": "Ligue 1"
}


def get_football_matches(
    competition_code=""
):
    """Get upcoming football matches from Football-Data.org."""

    # Check this condition before continuing.
    if not FOOTBALL_DATA_API_KEY:

        # Return the result.
        return [], (
            "Football API token was not found. "
            "Check the .env file."
        )

    # Reject values that are not allowed.
    if competition_code not in FOOTBALL_COMPETITIONS:
        # Set up competition code.
        competition_code = ""

    # Set up today.
    today = date.today()

    # Set up date from.
    date_from = today.isoformat()

    # Set up date to.
    date_to = (
        today + timedelta(days=30)
    ).isoformat()

    # All Competitions uses the general matches resource.
    # A selected competition uses that competition's
    # dedicated match resource.
    if competition_code:

        # Set up url.
        url = (
            f"{FOOTBALL_DATA_BASE_URL}"
            f"/competitions/{competition_code}"
            "/matches"
        )

    else:

        # Set up url.
        url = (
            f"{FOOTBALL_DATA_BASE_URL}"
            "/matches"
        )

    # Set up headers.
    headers = {
        "X-Auth-Token":
            FOOTBALL_DATA_API_KEY
    }

    # Store values used in the query.
    parameters = {
        "dateFrom": date_from,
        "dateTo": date_to
    }

    # Validate the value safely.
    try:

        # Set up response.
        response = requests.get(
            url,
            headers=headers,
            params=parameters,
            timeout=10
        )

        response.raise_for_status()

        # Set up data.
        data = response.json()

        # Set up matches.
        matches = data.get(
            "matches",
            []
        )

        # Set up upcoming statuses.
        upcoming_statuses = {
            "SCHEDULED",
            "TIMED"
        }

        # Set up upcoming matches.
        upcoming_matches = [
            match
            for match in matches
            if match.get("status")
            in upcoming_statuses
        ]

        upcoming_matches.sort(
            key=lambda match:
                match.get("utcDate", "")
        )

        # Keep the Dashboard compact.
        return upcoming_matches[:10], None

    except requests.RequestException as error:

        # Show the error in the terminal for debugging.
        print(
            "Football-Data.org API error:",
            error
        )

        # Return the result.
        return [], (
            "Football information is temporarily "
            "unavailable."
        )

    except ValueError as error:

        # Show the error in the terminal for debugging.
        print(
            "Football-Data.org JSON error:",
            error
        )

        # Return the result.
        return [], (
            "Football information is temporarily "
            "unavailable."
        )



# Login


@app.route("/", methods=["GET", "POST"])
def login():
    # Store the login error message.
    error = ""

    # Handle the submitted form.
    if request.method == "POST":

        # Get login details
        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        # Get the entered password.
        password = request.form.get(
            "password",
            ""
        )

        # Find the user
        user = get_user_by_email(email)

        # Check the login details
        if user and check_password_hash(
            user["password_hash"],
            password
        ):

            # Save user details in the session
            session["user_id"] = user["user_id"]
            session["name"] = user["name"]
            session["email"] = user["email"]
            session["role"] = user["role"]

            # Send viewers to their page
            if user["role"] == "Viewer":
                # Send the user to the correct page.
                return redirect(url_for("viewer"))

            # Send admins and coaches to the dashboard
            return redirect(url_for("dashboard"))

        # Store the login error message.
        error = "Invalid email or password."

    # Display the page with the current data.
    return render_template(
        "login.html",
        error=error
    )



# Dashboard


@app.route("/dashboard")
def dashboard():

    # Check login
    if "role" not in session:
        # Send the user to the correct page.
        return redirect(url_for("login"))

    # Block viewer access
    if session["role"] == "Viewer":
        # Send the user to the correct page.
        return redirect(url_for("viewer"))

    # Set up stats, attendance history.
    (
        stats,
        attendance_history,
        overdue_fee_summary
    ) = get_dashboard_data()

    # Get the selected football competition.
    selected_competition = request.args.get(
        "competition",
        ""
    ).strip()

    # Reject values that are not allowed.
    if selected_competition not in FOOTBALL_COMPETITIONS:
        # Get the selected football competition.
        selected_competition = ""

    # Set up football matches, football api error.
    (
        football_matches,
        football_api_error
    ) = get_football_matches(
        selected_competition
    )

    # Display the page with the current data.
    return render_template(
        "dashboard.html",
        stats=stats,
        attendance_history=attendance_history,
        overdue_fee_summary=overdue_fee_summary,
        football_matches=football_matches,
        football_api_error=football_api_error,
        football_competitions=FOOTBALL_COMPETITIONS,
        selected_competition=selected_competition
    )


# Player Management


@app.route("/players")
def players():

    # Check login
    if "role" not in session:
        # Send the user to the correct page.
        return redirect(url_for("login"))

    # Block viewer access
    if session["role"] == "Viewer":
        # Send the user to the correct page.
        return redirect(url_for("viewer"))

    # Get filters
    search = request.args.get(
        "search",
        ""
    ).strip()

    # Get the selected age group.
    age_group = request.args.get(
        "age_group",
        ""
    ).strip()

    # Get the selected team.
    team = request.args.get(
        "team",
        ""
    ).strip()

    # Open the database connection.
    connection = get_database_connection()

    # Start the player query
    query = """
        SELECT *
        FROM players
        WHERE 1 = 1
    """

    # Store values used in the query.
    parameters = []

    # Search by name or position
    if search:
        query += """
            AND (
                first_name LIKE ?
                OR last_name LIKE ?
                OR position LIKE ?
            )
        """

        # Set up search value.
        search_value = f"%{search}%"

        parameters.extend([
            search_value,
            search_value,
            search_value
        ])

    # Filter by age group
    if age_group:
        query += " AND age_group = ?"
        parameters.append(age_group)

    # Filter by team
    if team:
        query += " AND team = ?"
        parameters.append(team)

    # Sort players by name
    query += """
        ORDER BY
            last_name,
            first_name
    """

    # Run the player query.
    player_records = connection.execute(
        query,
        parameters
    ).fetchall()

    # Get teams for the filter
    teams = connection.execute("""
        SELECT DISTINCT team
        FROM players
        WHERE team != ''
        ORDER BY team
    """).fetchall()

    # Close the database connection.
    connection.close()

    # Display the page with the current data.
    return render_template(
        "players.html",
        players=player_records,
        teams=teams,
        search=search,
        selected_age_group=age_group,
        selected_team=team
    )



# Add Player


@app.route("/players/add", methods=["POST"])
def add_player():

    # Check login
    if "role" not in session:
        # Send the user to the correct page.
        return redirect(url_for("login"))

    # Only admins can add players
    if session["role"] != "Admin":
        # Send the user to the correct page.
        return redirect(url_for("players"))

    # Get player details
    first_name = request.form.get(
        "first_name",
        ""
    ).strip()

    # Get the player last name.
    last_name = request.form.get(
        "last_name",
        ""
    ).strip()

    # Get the player date of birth.
    date_of_birth = request.form.get(
        "date_of_birth",
        ""
    ).strip()

    # Get the selected age group.
    age_group = request.form.get(
        "age_group",
        ""
    ).strip()

    # Get the selected team.
    team = request.form.get(
        "team",
        ""
    ).strip()

    # Get the player position.
    position = request.form.get(
        "position",
        ""
    ).strip()

    # Get the contact phone number.
    contact_phone = request.form.get(
        "contact_phone",
        ""
    ).strip()

    # Get the emergency contact.
    emergency_contact = request.form.get(
        "emergency_contact",
        ""
    ).strip()

    # Get the medical notes.
    medical_notes = request.form.get(
        "medical_notes",
        ""
    ).strip()

    # Get the player status.
    registration_status = request.form.get(
        "registration_status",
        "Active"
    ).strip()

    # Check required fields
    if not all([
        first_name,
        last_name,
        date_of_birth,
        age_group,
        team,
        position
    ]):
        # Send the user to the correct page.
        return redirect(url_for("players"))

    # Open the database connection.
    connection = get_database_connection()

    # Add the player
    connection.execute("""
        INSERT INTO players (
            first_name,
            last_name,
            date_of_birth,
            age_group,
            team,
            position,
            contact_phone,
            emergency_contact,
            medical_notes,
            registration_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        first_name,
        last_name,
        date_of_birth,
        age_group,
        team,
        position,
        contact_phone,
        emergency_contact,
        medical_notes,
        registration_status
    ))

    # Save the database changes.
    connection.commit()
    # Close the database connection.
    connection.close()

    # Send the user to the correct page.
    return redirect(url_for("players"))



# Edit Player


@app.route(
    "/players/edit/<int:player_id>",
    methods=["POST"]
)
def edit_player(player_id):

    # Check login
    if "role" not in session:
        # Send the user to the correct page.
        return redirect(url_for("login"))

    # Only admins can edit players
    if session["role"] != "Admin":
        # Send the user to the correct page.
        return redirect(url_for("players"))

    # Open the database connection.
    connection = get_database_connection()

    # Update the player
    connection.execute("""
        UPDATE players
        SET first_name = ?,
            last_name = ?,
            date_of_birth = ?,
            age_group = ?,
            team = ?,
            position = ?,
            contact_phone = ?,
            emergency_contact = ?,
            medical_notes = ?,
            registration_status = ?
        WHERE player_id = ?
    """, (
        request.form.get(
            "first_name",
            ""
        ).strip(),

        request.form.get(
            "last_name",
            ""
        ).strip(),

        request.form.get(
            "date_of_birth",
            ""
        ).strip(),

        request.form.get(
            "age_group",
            ""
        ).strip(),

        request.form.get(
            "team",
            ""
        ).strip(),

        request.form.get(
            "position",
            ""
        ).strip(),

        request.form.get(
            "contact_phone",
            ""
        ).strip(),

        request.form.get(
            "emergency_contact",
            ""
        ).strip(),

        request.form.get(
            "medical_notes",
            ""
        ).strip(),

        request.form.get(
            "registration_status",
            "Active"
        ).strip(),

        player_id
    ))

    # Save the database changes.
    connection.commit()
    # Close the database connection.
    connection.close()

    # Send the user to the correct page.
    return redirect(url_for("players"))


# Delete Player


@app.route(
    "/players/delete/<int:player_id>",
    methods=["POST"]
)
def delete_player(player_id):

    # Check login
    if "role" not in session:
        # Send the user to the correct page.
        return redirect(url_for("login"))

    # Only admins can delete players
    if session["role"] != "Admin":
        # Send the user to the correct page.
        return redirect(url_for("players"))

    # Open the database connection.
    connection = get_database_connection()

    # Run the database command.
    connection.execute(
        """
        DELETE FROM players
        WHERE player_id = ?
        """,
        (player_id,)
    )

    # Save the database changes.
    connection.commit()
    # Close the database connection.
    connection.close()

    # Send the user to the correct page.
    return redirect(url_for("players"))



# Attendance Management


@app.route("/attendance", methods=["GET", "POST"])
def attendance():

    # Check login
    if "role" not in session:
        # Send the user to the correct page.
        return redirect(url_for("login"))

    # Block viewer access
    if session["role"] == "Viewer":
        # Send the user to the correct page.
        return redirect(url_for("viewer"))

    # Use today's date by default
    selected_date = request.values.get(
        "attendance_date",
        date.today().isoformat()
    ).strip()

    # Validate the selected date
    try:
        date.fromisoformat(selected_date)
    except ValueError:
        # Get the selected date.
        selected_date = date.today().isoformat()

    # Get the selected age group
    selected_age_group = request.values.get(
        "age_group",
        ""
    ).strip()

    # Allowed attendance statuses
    allowed_statuses = {
        "Present",
        "Absent",
        "Late"
    }

    # Open the database connection.
    connection = get_database_connection()

    # Save attendance
    if request.method == "POST":

        # Get the players being marked.
        player_ids = request.form.getlist(
            "player_ids"
        )

        # Get the coach name.
        coach_name = request.form.get(
            "coach_name",
            session.get("name", "")
        ).strip()

        # Process each saved record.
        for player_id_value in player_ids:

            # Ignore invalid ID values.
            if not player_id_value.isdigit():
                continue

            # Convert the player ID to a number.
            player_id = int(player_id_value)

            # Get the attendance status.
            attendance_status = request.form.get(
                f"attendance_{player_id}",
                ""
            ).strip()

            # Get the attendance note.
            attendance_note = request.form.get(
                f"note_{player_id}",
                ""
            ).strip()

            # Reject values that are not allowed.
            if attendance_status not in allowed_statuses:
                continue

            # Confirm that the player is active
            # and belongs to the selected age group
            player_exists = connection.execute("""
                SELECT player_id
                FROM players
                WHERE player_id = ?
                  AND registration_status = 'Active'
                  AND (? = '' OR age_group = ?)
            """, (
                player_id,
                selected_age_group,
                selected_age_group
            )).fetchone()

            # Stop if the record is not valid.
            if not player_exists:
                continue

            # Add or update attendance
            connection.execute("""
                INSERT INTO attendance (
                    player_id,
                    attendance_date,
                    attendance_status,
                    attendance_note,
                    coach_name
                )
                VALUES (?, ?, ?, ?, ?)

                ON CONFLICT (
                    player_id,
                    attendance_date
                )

                DO UPDATE SET
                    attendance_status =
                        excluded.attendance_status,
                    attendance_note =
                        excluded.attendance_note,
                    coach_name =
                        excluded.coach_name
            """, (
                player_id,
                selected_date,
                attendance_status,
                attendance_note,
                coach_name
            ))

        # Save the database changes.
        connection.commit()
        # Close the database connection.
        connection.close()

        # Send the user to the correct page.
        return redirect(
            url_for(
                "attendance",
                attendance_date=selected_date,
                age_group=selected_age_group,
                saved="1"
            )
        )

    # Do not display players until an age group
    # has been selected
    attendance_players = []

    if selected_age_group:

        # Set up attendance players.
        attendance_players = connection.execute("""
            SELECT
                players.player_id,
                players.first_name,
                players.last_name,
                players.age_group,
                players.team,
                players.position,
                attendance.attendance_status,
                attendance.attendance_note,
                attendance.coach_name

            FROM players

            LEFT JOIN attendance
                ON players.player_id =
                    attendance.player_id
                AND attendance.attendance_date = ?

            WHERE players.registration_status = 'Active'
              AND players.age_group = ?

            ORDER BY
                players.last_name,
                players.first_name
        """, (
            selected_date,
            selected_age_group
        )).fetchall()

    # Load active age groups directly from
    # the saved player database
    age_groups = connection.execute("""
        SELECT DISTINCT age_group
        FROM players
        WHERE age_group IS NOT NULL
          AND TRIM(age_group) != ''
          AND registration_status = 'Active'
        ORDER BY age_group
    """).fetchall()

    # Close the database connection.
    connection.close()

    # Display the page with the current data.
    return render_template(
        "attendance.html",
        players=attendance_players,
        age_groups=age_groups,
        selected_date=selected_date,
        selected_age_group=selected_age_group,
        saved=request.args.get("saved") == "1"
    )



# Teams Management


@app.route("/teams", methods=["GET", "POST"])
def teams():

    # Check login
    if "role" not in session:
        # Send the user to the correct page.
        return redirect(url_for("login"))

    # Block viewer access
    if session["role"] == "Viewer":
        # Send the user to the correct page.
        return redirect(url_for("viewer"))

    # Get the selected age group
    selected_age_group = request.values.get(
        "age_group",
        ""
    ).strip()

    # Get the selected formation
    selected_formation = request.values.get(
        "formation",
        "4-3-3"
    ).strip()

    # Set up allowed formations.
    allowed_formations = {
        "4-3-3",
        "4-4-2",
        "3-5-2"
    }

    # Each formation uses exactly 11 pitch positions.
    formation_slots = {
        "4-3-3": {
            "forward_left",
            "forward_centre",
            "forward_right",
            "midfield_left",
            "midfield_centre",
            "midfield_right",
            "defence_left",
            "defence_centre_left",
            "defence_centre_right",
            "defence_right",
            "goalkeeper"
        },

        "4-4-2": {
            "forward_left",
            "forward_right",
            "midfield_left",
            "midfield_centre_left",
            "midfield_centre_right",
            "midfield_right",
            "defence_left",
            "defence_centre_left",
            "defence_centre_right",
            "defence_right",
            "goalkeeper"
        },

        "3-5-2": {
            "forward_left",
            "forward_right",
            "midfield_left",
            "midfield_centre_left",
            "midfield_centre",
            "midfield_centre_right",
            "midfield_right",
            "defence_left",
            "defence_centre",
            "defence_right",
            "goalkeeper"
        }
    }

    # Reject values that are not allowed.
    if selected_formation not in allowed_formations:
        # Get the selected formation.
        selected_formation = "4-3-3"

    # Only accept position names that belong to
    # the currently selected formation.
    allowed_slots = formation_slots[selected_formation]

    connection = get_database_connection()

    # Make sure the team line-ups table exists.
    # This prevents the Teams page from failing
    # when database.py has not yet been run.
    connection.execute("""
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

    # Save the database changes.
    connection.commit()

    # Save the selected line-up
    if request.method == "POST":

        # Check this condition before continuing.
        if not selected_age_group:
            # Close the database connection.
            connection.close()

            # Send the user to the correct page.
            return redirect(
                url_for(
                    "teams",
                    formation=selected_formation
                )
            )

        # Remove the old saved line-up for this
        # age group and formation.
        connection.execute("""
            DELETE FROM team_lineups
            WHERE age_group = ?
              AND formation = ?
        """, (
            selected_age_group,
            selected_formation
        ))

        # Track players already used.
        used_player_ids = set()

        # Process each saved record.
        for slot_name in allowed_slots:

            # Get the selected player ID.
            player_id_value = request.form.get(
                f"lineup_{slot_name}",
                ""
            ).strip()

            # Ignore invalid ID values.
            if not player_id_value.isdigit():
                continue

            # Convert the player ID to a number.
            player_id = int(player_id_value)

            # Prevent the same player from being
            # placed into more than one slot.
            if player_id in used_player_ids:
                continue

            # Check that the player is active and
            # belongs to the selected age group.
            player = connection.execute("""
                SELECT player_id
                FROM players
                WHERE player_id = ?
                  AND age_group = ?
                  AND registration_status = 'Active'
            """, (
                player_id,
                selected_age_group
            )).fetchone()

            # Stop if the record is not valid.
            if not player:
                continue

            # Run the database command.
            connection.execute("""
                INSERT INTO team_lineups (
                    age_group,
                    formation,
                    slot_name,
                    player_id,
                    saved_by_user_id,
                    updated_at
                )
                VALUES (
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    CURRENT_TIMESTAMP
                )
            """, (
                selected_age_group,
                selected_formation,
                slot_name,
                player_id,
                session.get("user_id")
            ))

            used_player_ids.add(player_id)

        # Save the database changes.
        connection.commit()
        # Close the database connection.
        connection.close()

        # Send the user to the correct page.
        return redirect(
            url_for(
                "teams",
                age_group=selected_age_group,
                formation=selected_formation,
                saved="1"
            )
        )

    # Load active age groups from saved players
    age_groups = connection.execute("""
        SELECT DISTINCT age_group
        FROM players
        WHERE age_group IS NOT NULL
          AND TRIM(age_group) != ''
          AND registration_status = 'Active'
        ORDER BY age_group
    """).fetchall()

    # Do not display players until an age group
    # has been selected.
    team_players = []
    saved_lineup = {}

    # Check this condition before continuing.
    if selected_age_group:

        # Store players for the selected age group.
        team_players = connection.execute("""
            SELECT
                player_id,
                first_name,
                last_name,
                age_group,
                team,
                position

            FROM players

            WHERE registration_status = 'Active'
              AND age_group = ?

            ORDER BY
                last_name,
                first_name
        """, (
            selected_age_group,
        )).fetchall()

        # Get the saved line-up records.
        saved_records = connection.execute("""
            SELECT
                team_lineups.slot_name,
                players.player_id,
                players.first_name,
                players.last_name,
                players.position

            FROM team_lineups

            JOIN players
                ON team_lineups.player_id =
                    players.player_id

            WHERE team_lineups.age_group = ?
              AND team_lineups.formation = ?
              AND players.registration_status = 'Active'

            ORDER BY team_lineups.slot_name
        """, (
            selected_age_group,
            selected_formation
        )).fetchall()

        # Convert the saved rows into a dictionary
        # that teams.html can use by slot name.
        for record in saved_records:
            saved_lineup[record["slot_name"]] = {
                "player_id": record["player_id"],
                "player_name": (
                    f"{record['first_name']} "
                    f"{record['last_name']}"
                ),
                "position": record["position"]
            }

    # Close the database connection.
    connection.close()

    # Display the page with the current data.
    return render_template(
        "teams.html",
        age_groups=age_groups,
        selected_age_group=selected_age_group,
        selected_formation=selected_formation,
        players=team_players,
        saved_lineup=saved_lineup,
        saved=request.args.get("saved") == "1"
    )



# Fees Management


@app.route("/fees")
def fees():

    # Check login
    if "role" not in session:
        # Send the user to the correct page.
        return redirect(url_for("login"))

    # Block viewer access
    if session["role"] == "Viewer":
        # Send the user to the correct page.
        return redirect(url_for("viewer"))

    # Get the search value.
    search = request.args.get(
        "search",
        ""
    ).strip()

    # Get the selected fee status.
    selected_status = request.args.get(
        "status",
        ""
    ).strip()

    # Get the selected age group.
    selected_age_group = request.args.get(
        "age_group",
        ""
    ).strip()

    # Get the current year.
    current_year = date.today().year

    # Get the selected season.
    selected_season_value = request.args.get(
        "season",
        str(current_year)
    ).strip()

    # Validate the value safely.
    try:
        # Convert the season to a number.
        selected_season = int(selected_season_value)

    except ValueError:
        # Convert the season to a number.
        selected_season = current_year

    # Set up allowed statuses.
    allowed_statuses = {
        "",
        "Paid",
        "Part Payment",
        "Overdue",
        "Unpaid"
    }

    # Reject values that are not allowed.
    if selected_status not in allowed_statuses:
        # Get the selected fee status.
        selected_status = ""

    # Open the database connection.
    connection = get_database_connection()
    ensure_fees_table(connection)

    # Keep overdue statuses accurate as dates pass.
    refresh_fee_statuses(connection)
    refresh_overdue_fee_dashboard(connection)
    # Save the database changes.
    connection.commit()

    # Build the database query.
    query = """
        SELECT
            fees.fee_id,
            fees.player_id,
            fees.season,
            fees.amount_due,
            fees.amount_paid,
            fees.payment_status,
            fees.due_date,
            fees.payment_date,
            fees.notes,
            players.first_name,
            players.last_name,
            players.age_group,
            players.team

        FROM fees

        JOIN players
            ON fees.player_id = players.player_id

        WHERE fees.season = ?
    """

    # Store values used in the query.
    parameters = [
        selected_season
    ]

    # Check this condition before continuing.
    if search:
        query += """
            AND (
                players.first_name LIKE ?
                OR players.last_name LIKE ?
                OR (
                    players.first_name || ' ' ||
                    players.last_name
                ) LIKE ?
            )
        """

        # Set up search value.
        search_value = f"%{search}%"

        parameters.extend([
            search_value,
            search_value,
            search_value
        ])

    # Check this condition before continuing.
    if selected_status:
        query += """
            AND fees.payment_status = ?
        """

        parameters.append(
            selected_status
        )

    # Check this condition before continuing.
    if selected_age_group:
        query += """
            AND players.age_group = ?
        """

        parameters.append(
            selected_age_group
        )

    query += """
        ORDER BY
            players.last_name,
            players.first_name
    """

    # Run the fee query.
    fee_records = connection.execute(
        query,
        parameters
    ).fetchall()

    # Summary cards show the selected season.
    summary = connection.execute("""
        SELECT
            SUM(
                CASE
                    WHEN payment_status = 'Paid'
                    THEN 1
                    ELSE 0
                END
            ) AS paid_count,

            SUM(
                CASE
                    WHEN payment_status = 'Paid'
                    THEN amount_paid
                    ELSE 0
                END
            ) AS paid_total,

            SUM(
                CASE
                    WHEN payment_status = 'Part Payment'
                    THEN 1
                    ELSE 0
                END
            ) AS part_payment_count,

            SUM(
                CASE
                    WHEN payment_status = 'Part Payment'
                    THEN amount_paid
                    ELSE 0
                END
            ) AS part_payment_total,

            SUM(
                CASE
                    WHEN payment_status = 'Overdue'
                    THEN 1
                    ELSE 0
                END
            ) AS overdue_count,

            SUM(
                CASE
                    WHEN payment_status = 'Overdue'
                    THEN MAX(amount_due - amount_paid, 0)
                    ELSE 0
                END
            ) AS overdue_total

        FROM fees
        WHERE season = ?
    """, (
        selected_season,
    )).fetchone()

    # Get active players for fee records.
    players_for_fees = connection.execute("""
        SELECT
            player_id,
            first_name,
            last_name,
            age_group
        FROM players
        WHERE registration_status = 'Active'
        ORDER BY
            last_name,
            first_name
    """).fetchall()

    # Get age groups for the filter.
    age_groups = connection.execute("""
        SELECT DISTINCT age_group
        FROM players
        WHERE registration_status = 'Active'
          AND age_group IS NOT NULL
          AND TRIM(age_group) != ''
        ORDER BY age_group
    """).fetchall()

    # Get seasons already stored.
    saved_seasons = connection.execute("""
        SELECT DISTINCT season
        FROM fees
        ORDER BY season DESC
    """).fetchall()

    # Build the season list.
    seasons = {
        current_year - 2,
        current_year - 1,
        current_year,
        current_year + 1
    }

    # Process each saved record.
    for season_record in saved_seasons:
        seasons.add(
            int(season_record["season"])
        )

    # Build the season list.
    seasons = sorted(
        seasons,
        reverse=True
    )

    # Close the database connection.
    connection.close()

    # Display the page with the current data.
    return render_template(
        "fees.html",
        fees=fee_records,
        players=players_for_fees,
        age_groups=age_groups,
        seasons=seasons,
        paid_count=summary["paid_count"] or 0,
        paid_total=summary["paid_total"] or 0,
        part_payment_count=(
            summary["part_payment_count"] or 0
        ),
        part_payment_total=(
            summary["part_payment_total"] or 0
        ),
        overdue_count=summary["overdue_count"] or 0,
        overdue_total=summary["overdue_total"] or 0,
        search=search,
        selected_status=selected_status,
        selected_age_group=selected_age_group,
        selected_season=selected_season,
        saved=request.args.get("saved") == "1"
    )


@app.route("/fees/add", methods=["POST"])
def add_fee():

    # Check login
    if "role" not in session:
        # Send the user to the correct page.
        return redirect(url_for("login"))

    # Only admins can create fee records.
    if session["role"] != "Admin":
        # Send the user to the correct page.
        return redirect(url_for("fees"))

    # Get the selected player ID.
    player_id_value = request.form.get(
        "player_id",
        ""
    ).strip()

    # Set up season value.
    season_value = request.form.get(
        "season",
        ""
    ).strip()

    # Set up amount due value.
    amount_due_value = request.form.get(
        "amount_due",
        ""
    ).strip()

    # Set up amount paid value.
    amount_paid_value = request.form.get(
        "amount_paid",
        "0"
    ).strip()

    # Get the due date.
    due_date = request.form.get(
        "due_date",
        ""
    ).strip()

    # Get the notes.
    notes = request.form.get(
        "notes",
        ""
    ).strip()

    # Validate the value safely.
    try:
        # Convert the player ID to a number.
        player_id = int(player_id_value)
        # Set up season.
        season = int(season_value)
        # Get the amount due.
        amount_due = float(amount_due_value)
        # Set up amount paid.
        amount_paid = float(amount_paid_value)

    except (TypeError, ValueError):
        # Send the user to the correct page.
        return redirect(url_for("fees"))

    # Check this condition before continuing.
    if amount_due < 0 or amount_paid < 0:
        # Send the user to the correct page.
        return redirect(url_for("fees"))

    # A payment cannot exceed the amount due.
    amount_paid = min(
        amount_paid,
        amount_due
    )

    # Validate the value safely.
    try:
        date.fromisoformat(due_date)

    except ValueError:
        # Send the user to the correct page.
        return redirect(url_for("fees"))

    # Open the database connection.
    connection = get_database_connection()
    ensure_fees_table(connection)

    # Check the player can be selected.
    player = connection.execute("""
        SELECT player_id
        FROM players
        WHERE player_id = ?
          AND registration_status = 'Active'
    """, (
        player_id,
    )).fetchone()

    # Stop if the record is not valid.
    if not player:
        # Close the database connection.
        connection.close()
        # Send the user to the correct page.
        return redirect(url_for("fees"))

    # Work out the payment status.
    payment_status = calculate_fee_status(
        amount_due,
        amount_paid,
        due_date
    )

    # Set the payment date.
    payment_date = (
        date.today().isoformat()
        if amount_paid > 0
        else None
    )

    # One fee record is stored per player and season.
    connection.execute("""
        INSERT INTO fees (
            player_id,
            season,
            amount_due,
            amount_paid,
            payment_status,
            due_date,
            payment_date,
            notes,
            created_at,
            updated_at
        )
        VALUES (
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        )

        ON CONFLICT (
            player_id,
            season
        )

        DO UPDATE SET
            amount_due = excluded.amount_due,
            amount_paid = excluded.amount_paid,
            payment_status = excluded.payment_status,
            due_date = excluded.due_date,
            payment_date = excluded.payment_date,
            notes = excluded.notes,
            updated_at = CURRENT_TIMESTAMP
    """, (
        player_id,
        season,
        amount_due,
        amount_paid,
        payment_status,
        due_date,
        payment_date,
        notes
    ))

    refresh_overdue_fee_dashboard(connection)

    # Save the database changes.
    connection.commit()
    # Close the database connection.
    connection.close()

    # Send the user to the correct page.
    return redirect(
        url_for(
            "fees",
            season=season,
            saved="1"
        )
    )


@app.route(
    "/fees/payment/<int:fee_id>",
    methods=["POST"]
)
def add_fee_payment(fee_id):

    # Check login
    if "role" not in session:
        # Send the user to the correct page.
        return redirect(url_for("login"))

    # Only admins can record payments.
    if session["role"] != "Admin":
        # Send the user to the correct page.
        return redirect(url_for("fees"))

    # Get the payment amount.
    payment_amount_value = request.form.get(
        "payment_amount",
        ""
    ).strip()

    # Get the payment notes.
    payment_notes = request.form.get(
        "notes",
        ""
    ).strip()

    # Validate the value safely.
    try:
        # Set up payment amount.
        payment_amount = float(
            payment_amount_value
        )

    except (TypeError, ValueError):
        # Send the user to the correct page.
        return redirect(url_for("fees"))

    # Check this condition before continuing.
    if payment_amount <= 0:
        # Send the user to the correct page.
        return redirect(url_for("fees"))

    # Open the database connection.
    connection = get_database_connection()
    ensure_fees_table(connection)

    # Get the selected fee record.
    fee_record = connection.execute("""
        SELECT
            fee_id,
            season,
            amount_due,
            amount_paid,
            due_date,
            notes
        FROM fees
        WHERE fee_id = ?
    """, (
        fee_id,
    )).fetchone()

    # Check this condition before continuing.
    if not fee_record:
        # Close the database connection.
        connection.close()
        # Send the user to the correct page.
        return redirect(url_for("fees"))

    # Get the amount due.
    amount_due = float(
        fee_record["amount_due"]
    )

    # Get the amount already paid.
    existing_amount_paid = float(
        fee_record["amount_paid"]
    )

    # Calculate the remaining balance.
    remaining_amount = max(
        amount_due - existing_amount_paid,
        0
    )

    # Check this condition before continuing.
    if remaining_amount <= 0:
        # Close the database connection.
        connection.close()

        # Send the user to the correct page.
        return redirect(
            url_for(
                "fees",
                season=fee_record["season"]
            )
        )

    # Limit the payment to the remaining balance.
    accepted_payment = min(
        payment_amount,
        remaining_amount
    )

    # Calculate the new amount paid.
    new_amount_paid = (
        existing_amount_paid +
        accepted_payment
    )

    # Work out the payment status.
    payment_status = calculate_fee_status(
        amount_due,
        new_amount_paid,
        fee_record["due_date"]
    )

    # Get the existing payment notes.
    existing_notes = (
        fee_record["notes"] or ""
    ).strip()

    # Check this condition before continuing.
    if payment_notes and existing_notes:
        # Combine the payment notes.
        combined_notes = (
            existing_notes +
            "\n" +
            payment_notes
        )

    # Check this condition before continuing.
    elif payment_notes:
        # Combine the payment notes.
        combined_notes = payment_notes

    else:
        # Combine the payment notes.
        combined_notes = existing_notes

    # Run the database command.
    connection.execute("""
        UPDATE fees
        SET amount_paid = ?,
            payment_status = ?,
            payment_date = ?,
            notes = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE fee_id = ?
    """, (
        new_amount_paid,
        payment_status,
        date.today().isoformat(),
        combined_notes,
        fee_id
    ))

    refresh_overdue_fee_dashboard(connection)

    # Save the database changes.
    connection.commit()
    # Close the database connection.
    connection.close()

    # Send the user to the correct page.
    return redirect(
        url_for(
            "fees",
            season=fee_record["season"],
            saved="1"
        )
    )



# Assets Management


def ensure_assets_table(connection):
    """Create the assets table if it does not exist."""

    # Run the database command.
    connection.execute("""
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


def refresh_asset_dashboard(connection):
    """Update the dashboard asset count."""

    # Count the saved assets.
    asset_count = connection.execute("""
        SELECT COUNT(*)
        FROM assets
    """).fetchone()[0]

    # Run the database command.
    connection.execute("""
        UPDATE dashboard_stats
        SET club_assets = ?
        WHERE stat_id = 1
    """, (
        asset_count,
    ))


@app.route("/assets")
def assets():

    # Check login
    if "role" not in session:
        # Send the user to the correct page.
        return redirect(url_for("login"))

    # Block viewer access
    if session["role"] == "Viewer":
        # Send the user to the correct page.
        return redirect(url_for("viewer"))

    # Get the search value.
    search = request.args.get(
        "search",
        ""
    ).strip()

    # Get the selected asset category.
    selected_category = request.args.get(
        "category",
        ""
    ).strip()

    # Get the selected asset condition.
    selected_condition = request.args.get(
        "condition",
        ""
    ).strip()

    # Get the selected availability.
    selected_availability = request.args.get(
        "availability",
        ""
    ).strip()

    # Set up allowed categories.
    allowed_categories = {
        "",
        "Balls",
        "Bibs",
        "Cones",
        "Gear",
        "Equipment"
    }

    # Set up allowed conditions.
    allowed_conditions = {
        "",
        "Good",
        "Needs Review",
        "Damaged"
    }

    # Set up allowed availability.
    allowed_availability = {
        "",
        "Available",
        "In use",
        "Unavailable"
    }

    # Reject values that are not allowed.
    if selected_category not in allowed_categories:
        # Get the selected asset category.
        selected_category = ""

    # Reject values that are not allowed.
    if selected_condition not in allowed_conditions:
        # Get the selected asset condition.
        selected_condition = ""

    # Reject values that are not allowed.
    if selected_availability not in allowed_availability:
        # Get the selected availability.
        selected_availability = ""

    # Open the database connection.
    connection = get_database_connection()
    ensure_assets_table(connection)

    # Build the database query.
    query = """
        SELECT *
        FROM assets
        WHERE 1 = 1
    """

    # Store values used in the query.
    parameters = []

    # Check this condition before continuing.
    if search:
        query += """
            AND (
                name LIKE ?
                OR category LIKE ?
                OR allocated_to LIKE ?
            )
        """

        # Set up search value.
        search_value = f"%{search}%"

        parameters.extend([
            search_value,
            search_value,
            search_value
        ])

    # Check this condition before continuing.
    if selected_category:
        query += " AND category = ?"
        parameters.append(selected_category)

    # Check this condition before continuing.
    if selected_condition:
        query += " AND condition = ?"
        parameters.append(selected_condition)

    # Check this condition before continuing.
    if selected_availability:
        query += " AND availability = ?"
        parameters.append(selected_availability)

    query += """
        ORDER BY name
    """

    # Run the asset query.
    asset_records = connection.execute(
        query,
        parameters
    ).fetchall()

    # Close the database connection.
    connection.close()

    # Display the page with the current data.
    return render_template(
        "assets.html",
        assets=asset_records,
        search=search,
        selected_category=selected_category,
        selected_condition=selected_condition,
        selected_availability=selected_availability
    )


@app.route("/assets/add", methods=["POST"])
def add_asset():

    # Check login
    if "role" not in session:
        # Send the user to the correct page.
        return redirect(url_for("login"))

    # Only admins can add assets
    if session["role"] != "Admin":
        # Send the user to the correct page.
        return redirect(url_for("assets"))

    # Get the asset name.
    name = request.form.get(
        "name",
        ""
    ).strip()

    # Get the asset category.
    category = request.form.get(
        "category",
        ""
    ).strip()

    # Get the asset condition.
    condition = request.form.get(
        "condition",
        ""
    ).strip()

    # Get the asset availability.
    availability = request.form.get(
        "availability",
        ""
    ).strip()

    # Get who the asset is allocated to.
    allocated_to = request.form.get(
        "allocated_to",
        ""
    ).strip()

    # Set up allowed categories.
    allowed_categories = {
        "Balls",
        "Bibs",
        "Cones",
        "Gear",
        "Equipment"
    }

    # Set up allowed conditions.
    allowed_conditions = {
        "Good",
        "Needs Review",
        "Damaged"
    }

    # Set up allowed availability.
    allowed_availability = {
        "Available",
        "In use",
        "Unavailable"
    }

    # Reject values that are not allowed.
    if (
        not name
        or category not in allowed_categories
        or condition not in allowed_conditions
        or availability not in allowed_availability
    ):
        # Send the user to the correct page.
        return redirect(url_for("assets"))

    # Open the database connection.
    connection = get_database_connection()
    ensure_assets_table(connection)

    # Run the database command.
    connection.execute("""
        INSERT INTO assets (
            name,
            category,
            condition,
            availability,
            allocated_to,
            created_at,
            updated_at
        )
        VALUES (
            ?,
            ?,
            ?,
            ?,
            ?,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        )
    """, (
        name,
        category,
        condition,
        availability,
        allocated_to
    ))

    refresh_asset_dashboard(connection)

    # Save the database changes.
    connection.commit()
    # Close the database connection.
    connection.close()

    # Send the user to the correct page.
    return redirect(
        url_for(
            "assets",
            saved="1"
        )
    )


@app.route(
    "/assets/edit/<int:asset_id>",
    methods=["POST"]
)
def edit_asset(asset_id):

    # Check login
    if "role" not in session:
        # Send the user to the correct page.
        return redirect(url_for("login"))

    # Only admins can edit assets
    if session["role"] != "Admin":
        # Send the user to the correct page.
        return redirect(url_for("assets"))

    # Get the asset name.
    name = request.form.get(
        "name",
        ""
    ).strip()

    # Get the asset category.
    category = request.form.get(
        "category",
        ""
    ).strip()

    # Get the asset condition.
    condition = request.form.get(
        "condition",
        ""
    ).strip()

    # Get the asset availability.
    availability = request.form.get(
        "availability",
        ""
    ).strip()

    # Get who the asset is allocated to.
    allocated_to = request.form.get(
        "allocated_to",
        ""
    ).strip()

    # Set up allowed categories.
    allowed_categories = {
        "Balls",
        "Bibs",
        "Cones",
        "Gear",
        "Equipment"
    }

    # Set up allowed conditions.
    allowed_conditions = {
        "Good",
        "Needs Review",
        "Damaged"
    }

    # Set up allowed availability.
    allowed_availability = {
        "Available",
        "In use",
        "Unavailable"
    }

    # Reject values that are not allowed.
    if (
        not name
        or category not in allowed_categories
        or condition not in allowed_conditions
        or availability not in allowed_availability
    ):
        # Send the user to the correct page.
        return redirect(url_for("assets"))

    # Open the database connection.
    connection = get_database_connection()
    ensure_assets_table(connection)

    # Run the database command.
    connection.execute("""
        UPDATE assets
        SET name = ?,
            category = ?,
            condition = ?,
            availability = ?,
            allocated_to = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE asset_id = ?
    """, (
        name,
        category,
        condition,
        availability,
        allocated_to,
        asset_id
    ))

    refresh_asset_dashboard(connection)

    # Save the database changes.
    connection.commit()
    # Close the database connection.
    connection.close()

    # Send the user to the correct page.
    return redirect(
        url_for(
            "assets",
            saved="1"
        )
    )



# Training Sessions Management


def ensure_training_table(connection):
    """Create the training_sessions table if it does not exist."""

    # Run the database command.
    connection.execute("""
        CREATE TABLE IF NOT EXISTS training_sessions (
            session_id INTEGER PRIMARY KEY AUTOINCREMENT,

            session_date TEXT NOT NULL,

            team TEXT NOT NULL,

            team_type TEXT NOT NULL,

            session_type TEXT NOT NULL
                CHECK (
                    session_type IN (
                        'Training',
                        'Skills Session',
                        'Fitness',
                        'Tactical'
                    )
                ),

            session_time TEXT NOT NULL,

            location TEXT NOT NULL,

            coach_name TEXT NOT NULL,

            created_by_user_id INTEGER,

            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            updated_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (created_by_user_id)
                REFERENCES users(user_id)
                ON DELETE SET NULL
        )
    """)

    # Check the training table columns.
    training_columns = {
        column[1]
        for column in connection.execute(
            "PRAGMA table_info(training_sessions)"
        ).fetchall()
    }

    # Reject values that are not allowed.
    if "team_type" not in training_columns:
        # Run the database command.
        connection.execute("""
            ALTER TABLE training_sessions
            ADD COLUMN team_type TEXT NOT NULL DEFAULT ''
        """)
        # Save the database changes.
        connection.commit()


@app.route("/training")
def training():

    # Check login
    if "role" not in session:
        # Send the user to the correct page.
        return redirect(url_for("login"))

    # Viewer users use their separate read-only page.
    if session["role"] == "Viewer":
        # Send the user to the correct page.
        return redirect(url_for("viewer"))

    # Get the selected team.
    selected_team = request.args.get(
        "team",
        ""
    ).strip()

    # Set up allowed teams.
    allowed_teams = {
        "",
        "U10",
        "U12",
        "U14",
        "U16",
        "U18",
        "Senior"
    }

    # Reject values that are not allowed.
    if selected_team not in allowed_teams:
        # Get the selected team.
        selected_team = ""

    # Get the selected session type.
    selected_session_type = request.args.get(
        "session_type",
        ""
    ).strip()

    # Get the selected date.
    selected_date = request.args.get(
        "training_date",
        ""
    ).strip()

    # Set up allowed session types.
    allowed_session_types = {
        "",
        "Training",
        "Skills Session",
        "Fitness",
        "Tactical"
    }

    # Reject values that are not allowed.
    if selected_session_type not in allowed_session_types:
        # Get the selected session type.
        selected_session_type = ""

    # Validate date filter when one is supplied.
    if selected_date:
        # Validate the value safely.
        try:
            date.fromisoformat(selected_date)
        except ValueError:
            # Get the selected date.
            selected_date = ""

    # Open the database connection.
    connection = get_database_connection()
    ensure_training_table(connection)

    # Build the database query.
    query = """
        SELECT *
        FROM training_sessions
        WHERE 1 = 1
    """

    # Store values used in the query.
    parameters = []

    # Check this condition before continuing.
    if selected_team:
        query += """
            AND team = ?
        """
        parameters.append(selected_team)

    # Check this condition before continuing.
    if selected_session_type:
        query += """
            AND session_type = ?
        """
        parameters.append(selected_session_type)

    # Check this condition before continuing.
    if selected_date:
        query += """
            AND session_date = ?
        """
        parameters.append(selected_date)

    query += """
        ORDER BY
            session_date ASC,
            session_time ASC,
            team ASC
    """

    # Set up training records.
    training_records = connection.execute(
        query,
        parameters
    ).fetchall()

    # Use teams already stored against active players
    # so the Training filter stays linked to ClubSync data.
    team_records = connection.execute("""
        SELECT DISTINCT team
        FROM players
        WHERE team IS NOT NULL
          AND TRIM(team) != ''
          AND registration_status = 'Active'
        ORDER BY team
    """).fetchall()

    # Close the database connection.
    connection.close()

    # Display the page with the current data.
    return render_template(
        "training.html",
        training_sessions=training_records,
        teams=team_records,
        selected_team=selected_team,
        selected_session_type=selected_session_type,
        selected_date=selected_date,
        saved=request.args.get("saved") == "1"
    )


@app.route("/training/add", methods=["POST"])
def add_training():

    # Check login
    if "role" not in session:
        # Send the user to the correct page.
        return redirect(url_for("login"))

    # Admins and Coaches can create training sessions.
    if session["role"] not in ["Admin", "Coach"]:
        # Send the user to the correct page.
        return redirect(url_for("viewer"))

    # Get the training date.
    session_date = request.form.get(
        "session_date",
        ""
    ).strip()

    # Get the selected team.
    team = request.form.get(
        "team",
        ""
    ).strip()

    # Get the team type.
    team_type = request.form.get(
        "team_type",
        ""
    ).strip()

    # Get the session type.
    session_type = request.form.get(
        "session_type",
        ""
    ).strip()

    # Get the training time.
    session_time = request.form.get(
        "session_time",
        ""
    ).strip()

    # Get the training location.
    location = request.form.get(
        "location",
        ""
    ).strip()

    # Get the coach name.
    coach_name = request.form.get(
        "coach_name",
        ""
    ).strip()

    # Set up allowed teams.
    allowed_teams = {
        "U10",
        "U12",
        "U14",
        "U16",
        "U18",
        "Senior"
    }

    # Set up allowed session types.
    allowed_session_types = {
        "Training",
        "Skills Session",
        "Fitness",
        "Tactical"
    }

    # Reject values that are not allowed.
    if (
        not session_date
        or team not in allowed_teams
        or not team_type
        or session_type not in allowed_session_types
        or not session_time
        or not location
        or not coach_name
    ):
        # Send the user to the correct page.
        return redirect(url_for("training"))

    # Validate the value safely.
    try:
        date.fromisoformat(session_date)
    except ValueError:
        # Send the user to the correct page.
        return redirect(url_for("training"))

    # HTML time inputs should submit HH:MM.
    if (
        len(session_time) != 5
        or session_time[2] != ":"
        or not session_time[:2].isdigit()
        or not session_time[3:].isdigit()
    ):
        # Send the user to the correct page.
        return redirect(url_for("training"))

    # Set up hour.
    hour = int(session_time[:2])
    # Set up minute.
    minute = int(session_time[3:])

    # Check this condition before continuing.
    if hour > 23 or minute > 59:
        # Send the user to the correct page.
        return redirect(url_for("training"))

    # Open the database connection.
    connection = get_database_connection()
    ensure_training_table(connection)

    # Run the database command.
    connection.execute("""
        INSERT INTO training_sessions (
            session_date,
            team,
            team_type,
            session_type,
            session_time,
            location,
            coach_name,
            created_by_user_id,
            created_at,
            updated_at
        )
        VALUES (
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        )
    """, (
        session_date,
        team,
        team_type,
        session_type,
        session_time,
        location,
        coach_name,
        session.get("user_id")
    ))

    # Save the database changes.
    connection.commit()
    # Close the database connection.
    connection.close()

    # Send the user to the correct page.
    return redirect(
        url_for(
            "training",
            saved="1"
        )
    )


@app.route(
    "/training/edit/<int:session_id>",
    methods=["POST"]
)
def edit_training(session_id):

    # Check login
    if "role" not in session:
        # Send the user to the correct page.
        return redirect(url_for("login"))

    # Admins and Coaches can edit training sessions.
    if session["role"] not in ["Admin", "Coach"]:
        # Send the user to the correct page.
        return redirect(url_for("viewer"))

    # Get the training date.
    session_date = request.form.get(
        "session_date",
        ""
    ).strip()

    # Get the selected team.
    team = request.form.get(
        "team",
        ""
    ).strip()

    # Get the team type.
    team_type = request.form.get(
        "team_type",
        ""
    ).strip()

    # Get the session type.
    session_type = request.form.get(
        "session_type",
        ""
    ).strip()

    # Get the training time.
    session_time = request.form.get(
        "session_time",
        ""
    ).strip()

    # Get the training location.
    location = request.form.get(
        "location",
        ""
    ).strip()

    # Get the coach name.
    coach_name = request.form.get(
        "coach_name",
        ""
    ).strip()

    # Set up allowed teams.
    allowed_teams = {
        "U10",
        "U12",
        "U14",
        "U16",
        "U18",
        "Senior"
    }

    # Set up allowed session types.
    allowed_session_types = {
        "Training",
        "Skills Session",
        "Fitness",
        "Tactical"
    }

    # Reject values that are not allowed.
    if (
        not session_date
        or team not in allowed_teams
        or not team_type
        or session_type not in allowed_session_types
        or not session_time
        or not location
        or not coach_name
    ):
        # Send the user to the correct page.
        return redirect(url_for("training"))

    # Validate the value safely.
    try:
        date.fromisoformat(session_date)
    except ValueError:
        # Send the user to the correct page.
        return redirect(url_for("training"))

    # Ignore invalid ID values.
    if (
        len(session_time) != 5
        or session_time[2] != ":"
        or not session_time[:2].isdigit()
        or not session_time[3:].isdigit()
    ):
        # Send the user to the correct page.
        return redirect(url_for("training"))

    # Set up hour.
    hour = int(session_time[:2])
    # Set up minute.
    minute = int(session_time[3:])

    # Check this condition before continuing.
    if hour > 23 or minute > 59:
        # Send the user to the correct page.
        return redirect(url_for("training"))

    # Open the database connection.
    connection = get_database_connection()
    ensure_training_table(connection)

    # Run the database command.
    connection.execute("""
        UPDATE training_sessions
        SET session_date = ?,
            team = ?,
            team_type = ?,
            session_type = ?,
            session_time = ?,
            location = ?,
            coach_name = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE session_id = ?
    """, (
        session_date,
        team,
        team_type,
        session_type,
        session_time,
        location,
        coach_name,
        session_id
    ))

    # Save the database changes.
    connection.commit()
    # Close the database connection.
    connection.close()

    # Send the user to the correct page.
    return redirect(
        url_for(
            "training",
            saved="1"
        )
    )


@app.route(
    "/training/delete/<int:session_id>",
    methods=["POST"]
)
def delete_training(session_id):

    # Check login
    if "role" not in session:
        # Send the user to the correct page.
        return redirect(url_for("login"))

    # Admins and Coaches can delete training sessions.
    if session["role"] not in ["Admin", "Coach"]:
        # Send the user to the correct page.
        return redirect(url_for("viewer"))

    # Open the database connection.
    connection = get_database_connection()
    ensure_training_table(connection)

    # Run the database command.
    connection.execute("""
        DELETE FROM training_sessions
        WHERE session_id = ?
    """, (
        session_id,
    ))

    # Save the database changes.
    connection.commit()
    # Close the database connection.
    connection.close()

    # Send the user to the correct page.
    return redirect(url_for("training"))


# Viewer Page


@app.route("/viewer")
def viewer():

    # Check login
    if "role" not in session:
        # Send the user to the correct page.
        return redirect(url_for("login"))

    # Only Viewer accounts can use this page.
    if session["role"] != "Viewer":
        # Send the user to the correct page.
        return redirect(url_for("dashboard"))

    # Open the database connection.
    connection = get_database_connection()
    ensure_training_table(connection)

    # Viewers only see current and upcoming training sessions.
    training_sessions = connection.execute("""
        SELECT
            session_id,
            session_date,
            team,
            team_type,
            session_type,
            session_time,
            location,
            coach_name

        FROM training_sessions

        WHERE session_date >= ?

        ORDER BY
            session_date ASC,
            session_time ASC,
            team ASC
    """, (
        date.today().isoformat(),
    )).fetchall()

    # Close the database connection.
    connection.close()

    # Display the page with the current data.
    return render_template(
        "viewer.html",
        training_sessions=training_sessions
    )


# Logout


@app.route("/logout")
def logout():

    # Clear the current session.
    session.clear()

    # Send the user to the correct page.
    return redirect(url_for("login"))



# Run the Application


if __name__ == "__main__":
    app.run(debug=True)