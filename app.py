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



def ensure_fees_table(connection):
    """Create the fees table if it does not exist."""

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

    if amount_due > 0 and amount_paid >= amount_due:
        return "Paid"

    if due_date:
        try:
            parsed_due_date = date.fromisoformat(due_date)

            if parsed_due_date < date.today():
                return "Overdue"

        except ValueError:
            pass

    if amount_paid > 0:
        return "Part Payment"

    return "Unpaid"


def refresh_fee_statuses(connection):
    """Update stored fee statuses using current values."""

    fee_records = connection.execute("""
        SELECT
            fee_id,
            amount_due,
            amount_paid,
            due_date,
            payment_status
        FROM fees
    """).fetchall()

    for fee_record in fee_records:
        current_status = calculate_fee_status(
            float(fee_record["amount_due"]),
            float(fee_record["amount_paid"]),
            fee_record["due_date"]
        )

        if current_status != fee_record["payment_status"]:
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

    overdue_count = connection.execute("""
        SELECT COUNT(*)
        FROM fees
        WHERE payment_status = 'Overdue'
    """).fetchone()[0]

    connection.execute("""
        UPDATE dashboard_stats
        SET overdue_fees = ?
        WHERE stat_id = 1
    """, (
        overdue_count,
    ))


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

    # Validate the selected date
    try:
        date.fromisoformat(selected_date)
    except ValueError:
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

    connection = get_database_connection()

    # Save attendance
    if request.method == "POST":

        player_ids = request.form.getlist(
            "player_ids"
        )

        coach_name = request.form.get(
            "coach_name",
            session.get("name", "")
        ).strip()

        for player_id_value in player_ids:

            if not player_id_value.isdigit():
                continue

            player_id = int(player_id_value)

            attendance_status = request.form.get(
                f"attendance_{player_id}",
                ""
            ).strip()

            attendance_note = request.form.get(
                f"note_{player_id}",
                ""
            ).strip()

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

        connection.commit()
        connection.close()

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

    connection.close()

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
        return redirect(url_for("login"))

    # Block viewer access
    if session["role"] == "Viewer":
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

    if selected_formation not in allowed_formations:
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

    connection.commit()

    # Save the selected line-up
    if request.method == "POST":

        if not selected_age_group:
            connection.close()

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

        used_player_ids = set()

        for slot_name in allowed_slots:

            player_id_value = request.form.get(
                f"lineup_{slot_name}",
                ""
            ).strip()

            if not player_id_value.isdigit():
                continue

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

            if not player:
                continue

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

        connection.commit()
        connection.close()

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

    if selected_age_group:

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

    connection.close()

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
        return redirect(url_for("login"))

    # Block viewer access
    if session["role"] == "Viewer":
        return redirect(url_for("viewer"))

    search = request.args.get(
        "search",
        ""
    ).strip()

    selected_status = request.args.get(
        "status",
        ""
    ).strip()

    selected_age_group = request.args.get(
        "age_group",
        ""
    ).strip()

    current_year = date.today().year

    selected_season_value = request.args.get(
        "season",
        str(current_year)
    ).strip()

    try:
        selected_season = int(selected_season_value)

    except ValueError:
        selected_season = current_year

    allowed_statuses = {
        "",
        "Paid",
        "Part Payment",
        "Overdue",
        "Unpaid"
    }

    if selected_status not in allowed_statuses:
        selected_status = ""

    connection = get_database_connection()
    ensure_fees_table(connection)

    # Keep overdue statuses accurate as dates pass.
    refresh_fee_statuses(connection)
    refresh_overdue_fee_dashboard(connection)
    connection.commit()

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

    parameters = [
        selected_season
    ]

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

        search_value = f"%{search}%"

        parameters.extend([
            search_value,
            search_value,
            search_value
        ])

    if selected_status:
        query += """
            AND fees.payment_status = ?
        """

        parameters.append(
            selected_status
        )

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

    age_groups = connection.execute("""
        SELECT DISTINCT age_group
        FROM players
        WHERE registration_status = 'Active'
          AND age_group IS NOT NULL
          AND TRIM(age_group) != ''
        ORDER BY age_group
    """).fetchall()

    saved_seasons = connection.execute("""
        SELECT DISTINCT season
        FROM fees
        ORDER BY season DESC
    """).fetchall()

    seasons = {
        current_year - 2,
        current_year - 1,
        current_year,
        current_year + 1
    }

    for season_record in saved_seasons:
        seasons.add(
            int(season_record["season"])
        )

    seasons = sorted(
        seasons,
        reverse=True
    )

    connection.close()

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
        return redirect(url_for("login"))

    # Only admins can create fee records.
    if session["role"] != "Admin":
        return redirect(url_for("fees"))

    player_id_value = request.form.get(
        "player_id",
        ""
    ).strip()

    season_value = request.form.get(
        "season",
        ""
    ).strip()

    amount_due_value = request.form.get(
        "amount_due",
        ""
    ).strip()

    amount_paid_value = request.form.get(
        "amount_paid",
        "0"
    ).strip()

    due_date = request.form.get(
        "due_date",
        ""
    ).strip()

    notes = request.form.get(
        "notes",
        ""
    ).strip()

    try:
        player_id = int(player_id_value)
        season = int(season_value)
        amount_due = float(amount_due_value)
        amount_paid = float(amount_paid_value)

    except (TypeError, ValueError):
        return redirect(url_for("fees"))

    if amount_due < 0 or amount_paid < 0:
        return redirect(url_for("fees"))

    # A payment cannot exceed the amount due.
    amount_paid = min(
        amount_paid,
        amount_due
    )

    try:
        date.fromisoformat(due_date)

    except ValueError:
        return redirect(url_for("fees"))

    connection = get_database_connection()
    ensure_fees_table(connection)

    player = connection.execute("""
        SELECT player_id
        FROM players
        WHERE player_id = ?
          AND registration_status = 'Active'
    """, (
        player_id,
    )).fetchone()

    if not player:
        connection.close()
        return redirect(url_for("fees"))

    payment_status = calculate_fee_status(
        amount_due,
        amount_paid,
        due_date
    )

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

    connection.commit()
    connection.close()

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
        return redirect(url_for("login"))

    # Only admins can record payments.
    if session["role"] != "Admin":
        return redirect(url_for("fees"))

    payment_amount_value = request.form.get(
        "payment_amount",
        ""
    ).strip()

    payment_notes = request.form.get(
        "notes",
        ""
    ).strip()

    try:
        payment_amount = float(
            payment_amount_value
        )

    except (TypeError, ValueError):
        return redirect(url_for("fees"))

    if payment_amount <= 0:
        return redirect(url_for("fees"))

    connection = get_database_connection()
    ensure_fees_table(connection)

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

    if not fee_record:
        connection.close()
        return redirect(url_for("fees"))

    amount_due = float(
        fee_record["amount_due"]
    )

    existing_amount_paid = float(
        fee_record["amount_paid"]
    )

    remaining_amount = max(
        amount_due - existing_amount_paid,
        0
    )

    if remaining_amount <= 0:
        connection.close()

        return redirect(
            url_for(
                "fees",
                season=fee_record["season"]
            )
        )

    accepted_payment = min(
        payment_amount,
        remaining_amount
    )

    new_amount_paid = (
        existing_amount_paid +
        accepted_payment
    )

    payment_status = calculate_fee_status(
        amount_due,
        new_amount_paid,
        fee_record["due_date"]
    )

    existing_notes = (
        fee_record["notes"] or ""
    ).strip()

    if payment_notes and existing_notes:
        combined_notes = (
            existing_notes +
            "\n" +
            payment_notes
        )

    elif payment_notes:
        combined_notes = payment_notes

    else:
        combined_notes = existing_notes

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

    connection.commit()
    connection.close()

    return redirect(
        url_for(
            "fees",
            season=fee_record["season"],
            saved="1"
        )
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