import sqlite3

from datetime import date

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session
)

from werkzeug.security import check_password_hash



# Flask Setup


app = Flask(__name__)

# Session secret key
app.secret_key = "clubsync_secret_key"



# Database Functions


def get_database_connection():
    """Connect to the ClubSync database."""

    connection = sqlite3.connect("clubsync.db")

    # Access values using column names
    connection.row_factory = sqlite3.Row

    # Turn on foreign keys
    connection.execute("PRAGMA foreign_keys = ON")

    return connection


def get_user_by_email(email):
    """Find a user by email."""

    connection = get_database_connection()

    user = connection.execute(
        """
        SELECT *
        FROM users
        WHERE email = ?
        """,
        (email,)
    ).fetchone()

    connection.close()

    return user


def get_dashboard_stats():
    """Get the latest dashboard statistics."""

    connection = get_database_connection()

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

            overdue_fees,
            club_assets

        FROM dashboard_stats
        WHERE stat_id = 1
    """).fetchone()

    connection.close()

    return stats


def update_dashboard_stats(
    overdue_fees,
    club_assets
):
    """Update dashboard values managed by admins."""

    connection = get_database_connection()

    connection.execute("""
        UPDATE dashboard_stats
        SET overdue_fees = ?,
            club_assets = ?
        WHERE stat_id = 1
    """, (
        overdue_fees,
        club_assets
    ))

    connection.commit()
    connection.close()



# Login


@app.route("/", methods=["GET", "POST"])
def login():
    error = ""

    if request.method == "POST":

        # Get login details
        email = request.form.get(
            "email",
            ""
        ).strip().lower()

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
                return redirect(url_for("viewer"))

            # Send admins and coaches to the dashboard
            return redirect(url_for("dashboard"))

        error = "Invalid email or password."

    return render_template(
        "login.html",
        error=error
    )



# Dashboard


@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():

    # Check login
    if "role" not in session:
        return redirect(url_for("login"))

    # Block viewer access
    if session["role"] == "Viewer":
        return redirect(url_for("viewer"))

    if request.method == "POST":

        # Only admins can update these values
        if session["role"] != "Admin":
            return redirect(url_for("dashboard"))

        update_dashboard_stats(
            request.form.get("overdue_fees", 0),
            request.form.get("club_assets", 0)
        )

        return redirect(url_for("dashboard"))

    # Get dashboard data
    stats = get_dashboard_stats()

    return render_template(
        "dashboard.html",
        stats=stats
    )



# Player Management


@app.route("/players")
def players():

    # Check login
    if "role" not in session:
        return redirect(url_for("login"))

    # Block viewer access
    if session["role"] == "Viewer":
        return redirect(url_for("viewer"))

    # Get filters
    search = request.args.get(
        "search",
        ""
    ).strip()

    age_group = request.args.get(
        "age_group",
        ""
    ).strip()

    team = request.args.get(
        "team",
        ""
    ).strip()

    connection = get_database_connection()

    # Start the player query
    query = """
        SELECT *
        FROM players
        WHERE 1 = 1
    """

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

    connection.close()

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
        return redirect(url_for("login"))

    # Only admins can add players
    if session["role"] != "Admin":
        return redirect(url_for("players"))

    # Get player details
    first_name = request.form.get(
        "first_name",
        ""
    ).strip()

    last_name = request.form.get(
        "last_name",
        ""
    ).strip()

    date_of_birth = request.form.get(
        "date_of_birth",
        ""
    ).strip()

    age_group = request.form.get(
        "age_group",
        ""
    ).strip()

    team = request.form.get(
        "team",
        ""
    ).strip()

    position = request.form.get(
        "position",
        ""
    ).strip()

    contact_phone = request.form.get(
        "contact_phone",
        ""
    ).strip()

    emergency_contact = request.form.get(
        "emergency_contact",
        ""
    ).strip()

    medical_notes = request.form.get(
        "medical_notes",
        ""
    ).strip()

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
        return redirect(url_for("players"))

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

    connection.commit()
    connection.close()

    return redirect(url_for("players"))



# Edit Player


@app.route(
    "/players/edit/<int:player_id>",
    methods=["POST"]
)
def edit_player(player_id):

    # Check login
    if "role" not in session:
        return redirect(url_for("login"))

    # Only admins can edit players
    if session["role"] != "Admin":
        return redirect(url_for("players"))

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

    connection.commit()
    connection.close()

    return redirect(url_for("players"))


# Delete Player


@app.route(
    "/players/delete/<int:player_id>",
    methods=["POST"]
)
def delete_player(player_id):

    # Check login
    if "role" not in session:
        return redirect(url_for("login"))

    # Only admins can delete players
    if session["role"] != "Admin":
        return redirect(url_for("players"))

    connection = get_database_connection()

    connection.execute(
        """
        DELETE FROM players
        WHERE player_id = ?
        """,
        (player_id,)
    )

    connection.commit()
    connection.close()

    return redirect(url_for("players"))



# Attendance Management


@app.route("/attendance", methods=["GET", "POST"])
def attendance():

    # Check login
    if "role" not in session:
        return redirect(url_for("login"))

    # Block viewer access
    if session["role"] == "Viewer":
        return redirect(url_for("viewer"))

    # Use today's date by default
    selected_date = request.values.get(
        "attendance_date",
        date.today().isoformat()
    ).strip()

    # Check the date
    try:
        date.fromisoformat(selected_date)
    except ValueError:
        selected_date = date.today().isoformat()

    # Get filters
    selected_team = request.values.get(
        "team",
        ""
    ).strip()

    search = request.values.get(
        "search",
        ""
    ).strip()

    # Allowed attendance statuses
    allowed_statuses = {
        "Present",
        "Absent",
        "Late"
    }

    connection = get_database_connection()

    # Save attendance
    if request.method == "POST":

        # Get displayed player IDs
        player_ids = request.form.getlist(
            "player_ids"
        )

        for player_id_value in player_ids:

            # Skip invalid IDs
            if not player_id_value.isdigit():
                continue

            player_id = int(player_id_value)

            # Get the selected status
            attendance_status = request.form.get(
                f"attendance_{player_id}",
                ""
            ).strip()

            # Skip invalid statuses
            if attendance_status not in allowed_statuses:
                continue

            # Check the player is active
            player_exists = connection.execute("""
                SELECT player_id
                FROM players
                WHERE player_id = ?
                  AND registration_status = 'Active'
            """, (
                player_id,
            )).fetchone()

            if not player_exists:
                continue

            # Add or update attendance
            connection.execute("""
                INSERT INTO attendance (
                    player_id,
                    attendance_date,
                    attendance_status
                )
                VALUES (?, ?, ?)

                ON CONFLICT (
                    player_id,
                    attendance_date
                )

                DO UPDATE SET
                    attendance_status =
                        excluded.attendance_status
            """, (
                player_id,
                selected_date,
                attendance_status
            ))

        connection.commit()
        connection.close()

        # Prevent the form from saving twice
        return redirect(
            url_for(
                "attendance",
                attendance_date=selected_date,
                team=selected_team,
                search=search,
                saved="1"
            )
        )

    # Get players and attendance for the date
    attendance_query = """
        SELECT
            players.player_id,
            players.first_name,
            players.last_name,
            players.age_group,
            players.team,
            players.position,
            attendance.attendance_status

        FROM players

        LEFT JOIN attendance
            ON players.player_id =
                attendance.player_id
            AND attendance.attendance_date = ?

        WHERE players.registration_status = 'Active'
    """

    attendance_parameters = [
        selected_date
    ]

    # Filter by team
    if selected_team:
        attendance_query += """
            AND players.team = ?
        """

        attendance_parameters.append(
            selected_team
        )

    # Search by name or position
    if search:
        attendance_query += """
            AND (
                players.first_name LIKE ?
                OR players.last_name LIKE ?
                OR players.position LIKE ?
            )
        """

        search_value = f"%{search}%"

        attendance_parameters.extend([
            search_value,
            search_value,
            search_value
        ])

    # Sort by team and name
    attendance_query += """
        ORDER BY
            players.team,
            players.last_name,
            players.first_name
    """

    attendance_players = connection.execute(
        attendance_query,
        attendance_parameters
    ).fetchall()

    # Get active teams
    teams = connection.execute("""
        SELECT DISTINCT team
        FROM players
        WHERE team != ''
          AND registration_status = 'Active'
        ORDER BY team
    """).fetchall()

    # Get the 10 latest attendance dates
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

            SUM(
                CASE
                    WHEN attendance_status = 'Absent'
                    THEN 1
                    ELSE 0
                END
            ) AS absent_count,

            SUM(
                CASE
                    WHEN attendance_status = 'Late'
                    THEN 1
                    ELSE 0
                END
            ) AS late_count

        FROM attendance

        GROUP BY attendance_date

        ORDER BY attendance_date DESC

        LIMIT 10
    """).fetchall()

    connection.close()

    return render_template(
        "attendance.html",
        players=attendance_players,
        teams=teams,
        selected_date=selected_date,
        selected_team=selected_team,
        search=search,
        attendance_history=attendance_history,
        saved=request.args.get("saved") == "1"
    )



# Viewer Page


@app.route("/viewer")
def viewer():

    # Check login
    if "role" not in session:
        return redirect(url_for("login"))

    # Only viewers can use this page
    if session["role"] != "Viewer":
        return redirect(url_for("dashboard"))

    return render_template("viewer.html")



# Logout


@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))



# Run the Application


if __name__ == "__main__":
    app.run(debug=True)