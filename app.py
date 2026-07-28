# ==========================================
# ClubSync - Flask Web Application
# Author: Harry S
# Description:
# This application manages the Western Tigers
# Soccer Club by providing secure login,
# dashboard management and player management.
# ==========================================

# ==========================================
# Import required libraries
# ==========================================

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


# ==========================================
# Create the Flask application
# ==========================================

app = Flask(__name__)

# Secret key used to securely manage user sessions
app.secret_key = "clubsync_secret_key"


# ==========================================
# Database Functions
# ==========================================

# Create and return a connection to the SQLite database
def get_database_connection():

    connection = sqlite3.connect("clubsync.db")
    connection.row_factory = sqlite3.Row

    return connection


# Retrieve a user's information using their email address
# This function is used during login authentication
def get_user_by_email(email):

    connection = get_database_connection()

    user = connection.execute(
        "SELECT * FROM users WHERE email = ?",
        (email,)
    ).fetchone()

    connection.close()

    return user


# Retrieve dashboard statistics from the database
# The total number of players is automatically calculated
# from the players table.
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


# Update the editable dashboard statistics.
# Only administrators are permitted to update
# these values.
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


# ==========================================
# Login Page
# Authenticates users and redirects them
# according to their assigned role.
# ==========================================

@app.route("/", methods=["GET", "POST"])
def login():

    error = ""

    if request.method == "POST":

        # Retrieve login details entered by the user
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        # Search for the user in the database
        user = get_user_by_email(email)

        # Verify the password matches the stored hash
        if user and check_password_hash(

            user["password_hash"],
            password

        ):

            # Store user information in the session
            session["user_id"] = user["user_id"]
            session["name"] = user["name"]
            session["email"] = user["email"]
            session["role"] = user["role"]

            # Redirect Viewer users to the Viewer page
            if user["role"] == "Viewer":
                return redirect(url_for("viewer"))

            # Redirect Admin and Coach users
            # to the Dashboard
            return redirect(url_for("dashboard"))

        # Display an error if authentication fails
        error = "Invalid email or password."

    return render_template(
        "login.html",
        error=error
    )


# ==========================================
# Dashboard Page
# Displays club statistics and allows
# administrators to update dashboard values.
# ==========================================

@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():

    # Prevent unauthorised access
    if "role" not in session:
        return redirect(url_for("login"))

    # Viewer accounts cannot access the dashboard
    if session["role"] == "Viewer":
        return redirect(url_for("viewer"))

    # Process updates submitted by administrators
    if request.method == "POST":

        if session["role"] != "Admin":
            return redirect(url_for("dashboard"))

        update_dashboard_stats(

            request.form.get("attendance_records"),
            request.form.get("overdue_fees"),
            request.form.get("club_assets")

        )

        return redirect(url_for("dashboard"))

    # Retrieve the latest dashboard statistics
    stats = get_dashboard_stats()

    return render_template(

        "dashboard.html",
        stats=stats

    )

# ==========================================
# Player Management Page
# Displays all player records and provides
# search and filtering functionality.
# ==========================================

@app.route("/players")
def players():

    # Prevent unauthorised access
    if "role" not in session:
        return redirect(url_for("login"))

    # Viewer accounts cannot access player management
    if session["role"] == "Viewer":
        return redirect(url_for("viewer"))

    # Retrieve search and filter values
    search = request.args.get("search", "").strip()
    age_group = request.args.get("age_group", "").strip()
    team = request.args.get("team", "").strip()

    connection = get_database_connection()

    # Base SQL query
    query = """
        SELECT *
        FROM players
        WHERE 1 = 1
    """

    parameters = []

    # Apply search filter
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

    # Apply age group filter
    if age_group:
        query += " AND age_group = ?"
        parameters.append(age_group)

    # Apply team filter
    if team:
        query += " AND team = ?"
        parameters.append(team)

    # Sort players alphabetically
    query += " ORDER BY last_name, first_name"

    player_records = connection.execute(
        query,
        parameters
    ).fetchall()

    # Retrieve unique teams for the filter dropdown
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


# ==========================================
# Add Player
# Creates a new player record in the database.
# Only administrators can add players.
# ==========================================

@app.route("/players/add", methods=["POST"])
def add_player():

    if "role" not in session:
        return redirect(url_for("login"))

    if session["role"] != "Admin":
        return redirect(url_for("players"))

    # Retrieve player information from the form
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

    # Validate required fields
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

    # Insert the new player into the database
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


# ==========================================
# Edit Player
# Updates an existing player's information.
# Only administrators can edit players.
# ==========================================

@app.route("/players/edit/<int:player_id>", methods=["POST"])
def edit_player(player_id):

    if "role" not in session:
        return redirect(url_for("login"))

    if session["role"] != "Admin":
        return redirect(url_for("players"))

    connection = get_database_connection()

    # Update the selected player
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


# ==========================================
# Delete Player
# Removes a player from the database.
# Only administrators can delete players.
# ==========================================

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


# ==========================================
# Viewer Page
# Displays the read-only interface for
# Viewer users such as parents or players.
# ==========================================

@app.route("/viewer")
def viewer():

    if "role" not in session:
        return redirect(url_for("login"))

    if session["role"] != "Viewer":
        return redirect(url_for("dashboard"))

    return render_template("viewer.html")


# ==========================================
# Logout
# Clears the current session and returns
# the user to the login page.
# ==========================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))


# ==========================================
# Run the Flask application
# ==========================================

if __name__ == "__main__":
    app.run(debug=True)