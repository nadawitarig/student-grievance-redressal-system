import csv
import io
import os
import re
import secrets
import sqlite3
from functools import wraps

import click
from flask import (
    Flask,
    Response,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_db, init_app as init_database, init_db


CATEGORIES = ("Academic", "Facilities", "Finance", "Harassment", "Hostel", "Other")
PRIORITIES = ("low", "medium", "high")
STATUSES = ("submitted", "in_review", "resolved", "rejected")
STATUS_LABELS = {
    "submitted": "Submitted",
    "in_review": "In Review",
    "resolved": "Resolved",
    "rejected": "Rejected",
}
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            flash("Please sign in to continue.", "warning")
            return redirect(url_for("login"))
        return view(**kwargs)

    return wrapped_view


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped_view(**kwargs):
        if g.user["role"] != "admin":
            abort(403)
        return view(**kwargs)

    return wrapped_view


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "development-key-change-before-deployment"),
        DATABASE=os.path.join(app.instance_path, "sgrs.sqlite"),
        MAX_CONTENT_LENGTH=1 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    )

    if test_config:
        app.config.update(test_config)

    os.makedirs(app.instance_path, exist_ok=True)
    init_database(app)
    with app.app_context():
        init_db()

    @app.before_request
    def load_user_and_protect_forms():
        user_id = session.get("user_id")
        g.user = (
            get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if user_id
            else None
        )

        if "_csrf_token" not in session:
            session["_csrf_token"] = secrets.token_urlsafe(32)

        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            submitted = request.form.get("csrf_token", "")
            expected = session.get("_csrf_token", "")
            if not submitted or not secrets.compare_digest(submitted, expected):
                abort(400, description="The form expired. Please reload the page and try again.")

    @app.context_processor
    def inject_template_values():
        return {
            "csrf_token": session.get("_csrf_token", ""),
            "categories": CATEGORIES,
            "priorities": PRIORITIES,
            "statuses": STATUSES,
            "status_labels": STATUS_LABELS,
        }

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "form-action 'self'; base-uri 'self'; frame-ancestors 'none'"
        )
        return response

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/register", methods=("GET", "POST"))
    def register():
        if g.user:
            return redirect_to_dashboard()

        if request.method == "POST":
            full_name = request.form.get("full_name", "").strip()
            student_number = request.form.get("student_id", "").strip().upper()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")

            error = None
            if len(full_name) < 3 or len(full_name) > 100:
                error = "Enter a valid full name (3–100 characters)."
            elif len(student_number) < 3 or len(student_number) > 30:
                error = "Enter a valid student ID (3–30 characters)."
            elif not EMAIL_PATTERN.match(email):
                error = "Enter a valid email address."
            elif len(password) < 8:
                error = "Password must contain at least 8 characters."
            elif password != confirm_password:
                error = "Passwords do not match."

            if error is None:
                try:
                    db = get_db()
                    db.execute(
                        """
                        INSERT INTO users (full_name, student_id, email, password_hash, role)
                        VALUES (?, ?, ?, ?, 'student')
                        """,
                        (full_name, student_number, email, generate_password_hash(password)),
                    )
                    db.commit()
                except sqlite3.IntegrityError:
                    error = "That student ID or email is already registered."

            if error is None:
                flash("Account created successfully. You can now sign in.", "success")
                return redirect(url_for("login"))
            flash(error, "error")

        return render_template("register.html")

    @app.route("/login", methods=("GET", "POST"))
    def login():
        if g.user:
            return redirect_to_dashboard()

        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

            if user is None or not check_password_hash(user["password_hash"], password):
                flash("Incorrect email or password.", "error")
            else:
                session.clear()
                session["user_id"] = user["id"]
                session["_csrf_token"] = secrets.token_urlsafe(32)
                flash(f"Welcome back, {user['full_name'].split()[0]}!", "success")
                return redirect_to_dashboard(user)

        return render_template("login.html")

    @app.post("/logout")
    @login_required
    def logout():
        session.clear()
        flash("You have been signed out.", "success")
        return redirect(url_for("index"))

    @app.route("/student/dashboard")
    @login_required
    def student_dashboard():
        if g.user["role"] == "admin":
            return redirect(url_for("admin_dashboard"))

        db = get_db()
        grievances = db.execute(
            """
            SELECT * FROM grievances
            WHERE student_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (g.user["id"],),
        ).fetchall()
        counts = {status: 0 for status in STATUSES}
        for grievance in grievances:
            counts[grievance["status"]] += 1
        return render_template("student_dashboard.html", grievances=grievances, counts=counts)

    @app.route("/grievances/new", methods=("GET", "POST"))
    @login_required
    def new_grievance():
        if g.user["role"] == "admin":
            abort(403)

        if request.method == "POST":
            title = request.form.get("title", "").strip()
            category = request.form.get("category", "")
            priority = request.form.get("priority", "medium")
            description = request.form.get("description", "").strip()

            error = None
            if len(title) < 5 or len(title) > 120:
                error = "Title must contain 5–120 characters."
            elif category not in CATEGORIES:
                error = "Select a valid category."
            elif priority not in PRIORITIES:
                error = "Select a valid priority."
            elif len(description) < 20 or len(description) > 2000:
                error = "Description must contain 20–2,000 characters."

            if error is None:
                reference_no = generate_reference()
                db = get_db()
                cursor = db.execute(
                    """
                    INSERT INTO grievances
                        (reference_no, student_id, title, category, description, priority)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (reference_no, g.user["id"], title, category, description, priority),
                )
                grievance_id = cursor.lastrowid
                db.execute(
                    """
                    INSERT INTO grievance_updates
                        (grievance_id, author_id, old_status, new_status, message)
                    VALUES (?, ?, NULL, 'submitted', ?)
                    """,
                    (grievance_id, g.user["id"], "Grievance submitted by the student."),
                )
                db.commit()
                flash(f"Grievance {reference_no} submitted successfully.", "success")
                return redirect(url_for("grievance_detail", grievance_id=grievance_id))

            flash(error, "error")

        return render_template("new_grievance.html")

    @app.route("/grievances/<int:grievance_id>")
    @login_required
    def grievance_detail(grievance_id):
        grievance = get_grievance_or_404(grievance_id)
        if g.user["role"] != "admin" and grievance["student_id"] != g.user["id"]:
            abort(403)

        updates = get_db().execute(
            """
            SELECT grievance_updates.*, users.full_name AS author_name,
                   users.role AS author_role
            FROM grievance_updates
            JOIN users ON users.id = grievance_updates.author_id
            WHERE grievance_updates.grievance_id = ?
            ORDER BY grievance_updates.created_at ASC, grievance_updates.id ASC
            """,
            (grievance_id,),
        ).fetchall()
        return render_template("grievance_detail.html", grievance=grievance, updates=updates)

    @app.route("/admin/dashboard")
    @admin_required
    def admin_dashboard():
        filters = parse_filters()
        grievances = query_grievances(filters)
        db = get_db()
        summary_rows = db.execute(
            "SELECT status, COUNT(*) AS total FROM grievances GROUP BY status"
        ).fetchall()
        counts = {status: 0 for status in STATUSES}
        for row in summary_rows:
            counts[row["status"]] = row["total"]
        return render_template(
            "admin_dashboard.html", grievances=grievances, counts=counts, filters=filters
        )

    @app.route("/admin/grievances/<int:grievance_id>", methods=("GET", "POST"))
    @admin_required
    def admin_grievance(grievance_id):
        grievance = get_grievance_or_404(grievance_id)

        if request.method == "POST":
            new_status = request.form.get("status", "")
            message = request.form.get("message", "").strip()

            if new_status not in STATUSES:
                flash("Select a valid status.", "error")
            elif message and len(message) > 1000:
                flash("Response must not exceed 1,000 characters.", "error")
            elif new_status == grievance["status"] and not message:
                flash("Change the status or add a response before saving.", "warning")
            else:
                if not message:
                    message = f"Status changed to {STATUS_LABELS[new_status]}."
                db = get_db()
                db.execute(
                    """
                    UPDATE grievances
                    SET status = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (new_status, grievance_id),
                )
                db.execute(
                    """
                    INSERT INTO grievance_updates
                        (grievance_id, author_id, old_status, new_status, message)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (grievance_id, g.user["id"], grievance["status"], new_status, message),
                )
                db.commit()
                flash("Grievance updated successfully.", "success")
                return redirect(url_for("admin_grievance", grievance_id=grievance_id))

        updates = get_db().execute(
            """
            SELECT grievance_updates.*, users.full_name AS author_name,
                   users.role AS author_role
            FROM grievance_updates
            JOIN users ON users.id = grievance_updates.author_id
            WHERE grievance_updates.grievance_id = ?
            ORDER BY grievance_updates.created_at ASC, grievance_updates.id ASC
            """,
            (grievance_id,),
        ).fetchall()
        return render_template("admin_grievance.html", grievance=grievance, updates=updates)

    @app.get("/admin/export.csv")
    @admin_required
    def export_grievances():
        grievances = query_grievances(parse_filters())
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Reference",
                "Student",
                "Student ID",
                "Email",
                "Title",
                "Category",
                "Priority",
                "Status",
                "Created",
                "Updated",
            ]
        )
        for item in grievances:
            writer.writerow(
                [
                    safe_csv_cell(item["reference_no"]),
                    safe_csv_cell(item["student_name"]),
                    safe_csv_cell(item["student_number"]),
                    safe_csv_cell(item["student_email"]),
                    safe_csv_cell(item["title"]),
                    safe_csv_cell(item["category"]),
                    safe_csv_cell(item["priority"]),
                    safe_csv_cell(STATUS_LABELS[item["status"]]),
                    safe_csv_cell(item["created_at"]),
                    safe_csv_cell(item["updated_at"]),
                ]
            )
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=grievances.csv"},
        )

    @app.get("/health")
    def health():
        return {"service": "sgrs", "status": "ok"}

    @app.cli.command("create-admin")
    @click.option("--name", prompt="Full name")
    @click.option("--email", prompt="Email")
    @click.password_option(confirmation_prompt=True)
    def create_admin(name, email, password):
        """Create an administrator account without exposing a default password."""
        name = name.strip()
        email = email.strip().lower()
        if len(name) < 3 or not EMAIL_PATTERN.match(email) or len(password) < 8:
            raise click.ClickException("Use a valid name, email and password of 8+ characters.")
        try:
            db = get_db()
            db.execute(
                """
                INSERT INTO users (full_name, student_id, email, password_hash, role)
                VALUES (?, NULL, ?, ?, 'admin')
                """,
                (name, email, generate_password_hash(password)),
            )
            db.commit()
        except sqlite3.IntegrityError as exc:
            raise click.ClickException("That email is already registered.") from exc
        click.echo(f"Administrator account created for {email}.")

    @app.errorhandler(400)
    def bad_request(error):
        return render_template("error.html", code=400, message=error.description), 400

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("error.html", code=403, message="You cannot access this page."), 403

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("error.html", code=404, message="The requested page was not found."), 404

    return app


def redirect_to_dashboard(user=None):
    user = user or g.user
    endpoint = "admin_dashboard" if user["role"] == "admin" else "student_dashboard"
    return redirect(url_for(endpoint))


def generate_reference():
    return f"SGR-{secrets.token_hex(4).upper()}"


def safe_csv_cell(value):
    """Prevent spreadsheet applications from evaluating exported user input."""
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{text}"
    return text


def get_grievance_or_404(grievance_id):
    grievance = get_db().execute(
        """
        SELECT grievances.*, users.full_name AS student_name,
               users.student_id AS student_number, users.email AS student_email
        FROM grievances
        JOIN users ON users.id = grievances.student_id
        WHERE grievances.id = ?
        """,
        (grievance_id,),
    ).fetchone()
    if grievance is None:
        abort(404)
    return grievance


def parse_filters():
    status = request.args.get("status", "").strip()
    category = request.args.get("category", "").strip()
    query = request.args.get("q", "").strip()[:100]
    return {
        "status": status if status in STATUSES else "",
        "category": category if category in CATEGORIES else "",
        "q": query,
    }


def query_grievances(filters):
    sql = """
        SELECT grievances.*, users.full_name AS student_name,
               users.student_id AS student_number, users.email AS student_email
        FROM grievances
        JOIN users ON users.id = grievances.student_id
        WHERE 1 = 1
    """
    parameters = []

    if filters["status"]:
        sql += " AND grievances.status = ?"
        parameters.append(filters["status"])
    if filters["category"]:
        sql += " AND grievances.category = ?"
        parameters.append(filters["category"])
    if filters["q"]:
        sql += """
            AND (
                grievances.reference_no LIKE ? OR
                grievances.title LIKE ? OR
                users.full_name LIKE ? OR
                users.student_id LIKE ?
            )
        """
        search_term = f"%{filters['q']}%"
        parameters.extend([search_term] * 4)

    sql += " ORDER BY grievances.created_at DESC, grievances.id DESC"
    return get_db().execute(sql, parameters).fetchall()


app = create_app()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1")
