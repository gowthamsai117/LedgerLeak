import os
import sqlite3
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

import requests
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("LEDGER_DB", str(ROOT / "ledger.db")))
app = Flask(__name__)
app.secret_key = os.environ.get("LEDGER_SECRET", "development-only-change-me")
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL,
          role TEXT NOT NULL DEFAULT 'customer'
        );
        CREATE TABLE IF NOT EXISTS tickets (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          owner_id INTEGER NOT NULL,
          subject TEXT NOT NULL,
          body TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'Open',
          internal_note TEXT NOT NULL DEFAULT '',
          FOREIGN KEY(owner_id) REFERENCES users(id)
        );
        """)
        if con.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 0:
            # Seed only fictional public support data; no privileged account is seeded.
            con.execute("INSERT OR IGNORE INTO users(username,password_hash,role) VALUES(?,?,?)",
                        ("demo_customer", generate_password_hash("customer-demo-2026"), "customer"))
            uid = con.execute("SELECT id FROM users WHERE username='demo_customer'").fetchone()[0]
            con.execute("INSERT INTO tickets(owner_id,subject,body,status,internal_note) VALUES(?,?,?,?,?)",
                        (uid, "Duplicate payment review", "Please review the duplicate payment.", "Open",
                         "Internal routing: finance-review queue."))


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapped


@app.context_processor
def current_user():
    return {"logged_in": bool(session.get("user_id")), "username": session.get("username")}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if len(username) < 3 or len(password) < 10:
            flash("Use a username of at least 3 characters and a password of at least 10 characters.", "error")
            return render_template("login.html", mode="register")
        try:
            with db() as con:
                con.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
                            (username, generate_password_hash(password), "customer"))
            flash("Account created. Please sign in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("That username is already registered.", "error")
    return render_template("login.html", mode="register")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        with db() as con:
            user = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session.update(user_id=user["id"], username=user["username"], role=user["role"])
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html", mode="login")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    with db() as con:
        count = con.execute(
            "SELECT COUNT(*) FROM tickets WHERE owner_id=?", (session["user_id"],)
        ).fetchone()[0]
        status_rows = con.execute(
            "SELECT status, COUNT(*) AS amount FROM tickets WHERE owner_id=? GROUP BY status",
            (session["user_id"],)
        ).fetchall()
        recent_tickets = con.execute(
            "SELECT id, subject, status FROM tickets WHERE owner_id=? ORDER BY id DESC LIMIT 5",
            (session["user_id"],)
        ).fetchall()

    # Build dashboard visualizations from the signed-in customer's actual tickets.
    counts = {"open": 0, "in_progress": 0, "resolved": 0, "other": 0}
    for row in status_rows:
        status = (row["status"] or "").strip().lower().replace("-", " ").replace("_", " ")
        amount = row["amount"]
        if status in ("open", "new", "pending"):
            counts["open"] += amount
        elif status in ("in progress", "in review", "processing"):
            counts["in_progress"] += amount
        elif status in ("resolved", "closed", "complete", "completed"):
            counts["resolved"] += amount
        else:
            counts["other"] += amount

    def percent(value):
        return round((value / count) * 100, 1) if count else 0

    stats = {
        "total": count,
        "open": counts["open"],
        "in_progress": counts["in_progress"],
        "resolved": counts["resolved"],
        "other": counts["other"],
        "open_pct": percent(counts["open"]),
        "in_progress_pct": percent(counts["in_progress"]),
        "resolved_pct": percent(counts["resolved"]),
        "other_pct": percent(counts["other"]),
    }
    if count:
        open_end = counts["open"] / count * 360
        progress_end = open_end + counts["in_progress"] / count * 360
        resolved_end = progress_end + counts["resolved"] / count * 360
        stats["donut_style"] = (
            "conic-gradient(#5547d9 0deg {0}deg, #e6a23c {0}deg {1}deg, "
            "#159a72 {1}deg {2}deg, #a7b2c4 {2}deg 360deg)"
        ).format(round(open_end, 2), round(progress_end, 2), round(resolved_end, 2))
    else:
        stats["donut_style"] = "conic-gradient(#e7ebf3 0deg 360deg)"

    return render_template(
        "dashboard.html",
        ticket_count=count,
        stats=stats,
        recent_tickets=recent_tickets,
        role=session.get("role", "customer"),
    )


@app.route("/tickets")
@login_required
def tickets():
    with db() as con:
        rows = con.execute("SELECT id,subject,body,status FROM tickets WHERE owner_id=? ORDER BY id DESC",
                           (session["user_id"],)).fetchall()
    return render_template("tickets.html", tickets=rows)


@app.route("/ticket/<int:ticket_id>")
@login_required
def ticket_detail(ticket_id):
    with db() as con:
        ticket = con.execute("SELECT * FROM tickets WHERE id=? AND owner_id=?",
                             (ticket_id, session["user_id"])).fetchone()
    if ticket is None:
        abort(404)
    return render_template("ticket.html", ticket=ticket)


@app.route("/tickets/new", methods=["GET", "POST"])
@login_required
def new_ticket():
    if request.method == "POST":
        subject = request.form.get("subject", "").strip()
        body = request.form.get("body", "").strip()
        if not subject or not body:
            flash("Subject and description are required.", "error")
        else:
            with db() as con:
                con.execute("INSERT INTO tickets(owner_id,subject,body) VALUES(?,?,?)",
                            (session["user_id"], subject, body))
            flash("Ticket submitted.", "success")
            return redirect(url_for("tickets"))
    return render_template("new_ticket.html")


@app.route("/tools/preview", methods=["GET", "POST"])
@login_required
def preview():
    """Intentionally vulnerable lab feature: unrestricted server-side URL preview.
    Keep this application inside an isolated assessment VM/network only.
    """
    result = None
    if request.method == "POST":
        target = request.form.get("url", "")
        try:
            response = requests.get(target, timeout=3, allow_redirects=True)
            result = {"url": target, "status": response.status_code, "body": response.text[:4000]}
        except requests.RequestException as exc:
            result = {"url": target, "error": str(exc)}
    return render_template("preview.html", result=result)


@app.route("/internal/diagnostics")
def internal_diagnostics():
    # Fictional internal service intended for the local challenge chain.
    if request.remote_addr not in ("127.0.0.1", "::1"):
        abort(403)
    return {"service": "fintrust-routing", "status": "ok", "queue": "finance-review",
            "hint": "Routing metadata is maintained by the local operations service."}


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404), 404


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=False)
