import sqlite3

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session
)

from werkzeug.security import check_password_hash


app = Flask(__name__)
app.secret_key = "clubsync_secret_key"


def get_database_connection():
    connection = sqlite3.connect("clubsync.db")
    connection.row_factory = sqlite3.Row
    return connection


def get_user_by_email(email):
    connection = get_database_connection()

    user = connection.execute(
        "SELECT * FROM users WHERE email = ?",
        (email,)
    ).fetchone()

    connection.close()

    return user


def get_dashboard_stats():
    connection = get_database_connection()

    stats = connection.execute("""
        SELECT
            (
                SELECT COUNT(*)
                FROM players
            ) AS total_players,

            attendance_records,
            overdue_fees,
            club_assets

        FROM dashboard_stats
        WHERE stat_id = 1
    """).fetchone()

    connection.close()

    return stats


def update_dashboard_stats(
    attendance_records,
    overdue_fees,
    club_assets
):
    connection = get_database_connection()

    connection.execute("""
        UPDATE dashboard_stats
        SET attendance_records = ?,
            overdue_fees = ?,
            club_assets = ?
        WHERE stat_id = 1
    """, (
        attendance_records,
        overdue_fees,
        club_assets
    ))

    connection.commit()
    connection.close()


@app.route("/", methods=["GET", "POST"])
def login():
    error = ""

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = get_user_by_email(email)

        if user and check_password_hash(
            user["password_hash"],
            password
        ):
            session["user_id"] = user["user_id"]
            session["name"] = user["name"]
            session["email"] = user["email"]
            session["role"] = user["role"]

            if user["role"] == "Viewer":
                return redirect(url_for("viewer"))

            return redirect(url_for("dashboard"))

        error = "Invalid email or password."

    return render_template(
        "login.html",
        error=error
    )


@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if "role" not in session:
        return redirect(url_for("login"))

    if session["role"] == "Viewer":
        return redirect(url_for("viewer"))

    if request.method == "POST":
        if session["role"] != "Admin":
            return redirect(url_for("dashboard"))

        update_dashboard_stats(
            request.form.get("attendance_records"),
            request.form.get("overdue_fees"),
            request.form.get("club_assets")
        )

        return redirect(url_for("dashboard"))

    stats = get_dashboard_stats()

    return render_template(
        "dashboard.html",
        stats=stats
    )


@app.route("/players")
def players():
    if "role" not in session:
        return redirect(url_for("login"))

    if session["role"] == "Viewer":
        return redirect(url_for("viewer"))

    search = request.args.get("search", "").strip()
    age_group = request.args.get("age_group", "").strip()
    team = request.args.get("team", "").strip()

    connection = get_database_connection()

    query = """
        SELECT *
        FROM players
        WHERE 1 = 1
    """

    parameters = []

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

    if age_group:
        query += " AND age_group = ?"
        parameters.append(age_group)

    if team:
        query += " AND team = ?"
        parameters.append(team)

    query += " ORDER BY last_name, first_name"

    player_records = connection.execute(
        query,
        parameters
    ).fetchall()

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


@app.route("/players/add", methods=["POST"])
def add_player():
    if "role" not in session:
        return redirect(url_for("login"))

    if session["role"] != "Admin":
        return redirect(url_for("players"))

    first_name = request.form.get("first_name", "").strip()
    last_name = request.form.get("last_name", "").strip()
    date_of_birth = request.form.get("date_of_birth", "").strip()
    age_group = request.form.get("age_group", "").strip()
    team = request.form.get("team", "").strip()
    position = request.form.get("position", "").strip()
    contact_phone = request.form.get("contact_phone", "").strip()
    emergency_contact = request.form.get(
        "emergency_contact",
        ""
    ).strip()
    medical_notes = request.form.get("medical_notes", "").strip()
    registration_status = request.form.get(
        "registration_status",
        "Active"
    )

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


@app.route("/players/edit/<int:player_id>", methods=["POST"])
def edit_player(player_id):
    if "role" not in session:
        return redirect(url_for("login"))

    if session["role"] != "Admin":
        return redirect(url_for("players"))

    connection = get_database_connection()

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
        request.form.get("first_name", "").strip(),
        request.form.get("last_name", "").strip(),
        request.form.get("date_of_birth", "").strip(),
        request.form.get("age_group", "").strip(),
        request.form.get("team", "").strip(),
        request.form.get("position", "").strip(),
        request.form.get("contact_phone", "").strip(),
        request.form.get("emergency_contact", "").strip(),
        request.form.get("medical_notes", "").strip(),
        request.form.get("registration_status", "Active"),
        player_id
    ))

    connection.commit()
    connection.close()

    return redirect(url_for("players"))


@app.route("/players/delete/<int:player_id>", methods=["POST"])
def delete_player(player_id):
    if "role" not in session:
        return redirect(url_for("login"))

    if session["role"] != "Admin":
        return redirect(url_for("players"))

    connection = get_database_connection()

    connection.execute(
        "DELETE FROM players WHERE player_id = ?",
        (player_id,)
    )

    connection.commit()
    connection.close()

    return redirect(url_for("players"))



@app.route("/viewer")
def viewer():
    if "role" not in session:
        return redirect(url_for("login"))

    if session["role"] != "Viewer":
        return redirect(url_for("dashboard"))

    return render_template("viewer.html")



@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)