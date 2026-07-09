import sqlite3

from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.security import check_password_hash


app = Flask(__name__)
app.secret_key = "clubsync_secret_key"


def get_user_by_email(email):
    connection = sqlite3.connect("clubsync.db")
    connection.row_factory = sqlite3.Row
    cursor = connection.cursor()

    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    user = cursor.fetchone()

    connection.close()
    return user


def get_dashboard_stats():
    connection = sqlite3.connect("clubsync.db")
    connection.row_factory = sqlite3.Row
    cursor = connection.cursor()

    cursor.execute("SELECT * FROM dashboard_stats WHERE stat_id = 1")
    stats = cursor.fetchone()

    connection.close()
    return stats


def update_dashboard_stats(total_players, attendance_records, overdue_fees, club_assets):
    connection = sqlite3.connect("clubsync.db")
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE dashboard_stats
        SET total_players = ?, attendance_records = ?, overdue_fees = ?, club_assets = ?
        WHERE stat_id = 1
    """, (total_players, attendance_records, overdue_fees, club_assets))

    connection.commit()
    connection.close()


@app.route("/", methods=["GET", "POST"])
def login():
    error = ""

    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        user = get_user_by_email(email)

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["user_id"]
            session["name"] = user["name"]
            session["email"] = user["email"]
            session["role"] = user["role"]

            if user["role"] == "Viewer":
                return redirect(url_for("viewer"))

            return redirect(url_for("dashboard"))

        error = "Invalid email or password"

    return render_template("login.html", error=error)


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
            request.form.get("total_players"),
            request.form.get("attendance_records"),
            request.form.get("overdue_fees"),
            request.form.get("club_assets")
        )

        return redirect(url_for("dashboard"))

    stats = get_dashboard_stats()
    return render_template("dashboard.html", stats=stats)


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