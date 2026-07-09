from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)
app.secret_key = "clubsync_secret_key"

users = {
    "admin@clubsync.com": {"password": "admin123", "role": "Admin"},
    "coach@clubsync.com": {"password": "coach123", "role": "Coach"},
}

@app.route("/", methods=["GET", "POST"])
def login():
    error = ""

    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        if email in users and users[email]["password"] == password:
            session["user"] = email
            session["role"] = users[email]["role"]
            return redirect(url_for("dashboard"))
        else:
            error = "Invalid email or password"

    return render_template("login.html", error=error)

@app.route("/viewer-login")
def viewer_login():
    session["user"] = "viewer"
    session["role"] = "Viewer"
    return redirect(url_for("viewer"))

@app.route("/dashboard")
def dashboard():
    return "Dashboard page coming next"

@app.route("/viewer")
def viewer():
    return "Viewer page coming next"

if __name__ == "__main__":
    app.run(debug=True)