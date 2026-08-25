from app import safe_csv_cell
from database import get_db


def login(form_post, email, password):
    return form_post(
        "/login",
        {"email": email, "password": password},
        follow_redirects=True,
    )


def test_home_page_and_security_headers(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Every student concern deserves to be heard" in response.data
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_registration_login_and_submission(client, form_post, registered_student, app):
    response = login(form_post, **registered_student)
    assert response.status_code == 200
    assert b"My grievances" in response.data

    response = form_post(
        "/grievances/new",
        {
            "title": "Laboratory equipment is unavailable",
            "category": "Facilities",
            "priority": "high",
            "description": "Several required laboratory devices were unavailable during the scheduled session.",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Progress timeline" in response.data
    assert b"Laboratory equipment is unavailable" in response.data

    with app.app_context():
        grievance = get_db().execute("SELECT * FROM grievances").fetchone()
        assert grievance["status"] == "submitted"
        assert grievance["priority"] == "high"
        assert grievance["reference_no"].startswith("SGR-")


def test_student_cannot_access_admin_dashboard(client, form_post, registered_student):
    login(form_post, **registered_student)
    response = client.get("/admin/dashboard")
    assert response.status_code == 403


def test_admin_can_review_and_resolve_grievance(
    client, form_post, registered_student, app
):
    login(form_post, **registered_student)
    form_post(
        "/grievances/new",
        {
            "title": "Request for academic timetable clarification",
            "category": "Academic",
            "priority": "medium",
            "description": "The published timetable contains two overlapping laboratory sessions for our section.",
        },
    )

    form_post("/logout", {}, token_path="/student/dashboard")
    response = login(form_post, "admin@example.edu", "AdminPass123")
    assert b"Grievance queue" in response.data

    with app.app_context():
        grievance_id = get_db().execute("SELECT id FROM grievances").fetchone()["id"]

    response = form_post(
        f"/admin/grievances/{grievance_id}",
        {
            "status": "resolved",
            "message": "The timetable was corrected and republished by the academic office.",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Grievance updated successfully" in response.data
    assert b"The timetable was corrected" in response.data

    with app.app_context():
        grievance = get_db().execute(
            "SELECT status FROM grievances WHERE id = ?", (grievance_id,)
        ).fetchone()
        assert grievance["status"] == "resolved"


def test_post_without_csrf_is_rejected(client):
    response = client.post(
        "/login", data={"email": "admin@example.edu", "password": "AdminPass123"}
    )
    assert response.status_code == 400


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"service": "sgrs", "status": "ok"}


def test_csv_formula_values_are_neutralized():
    assert safe_csv_cell("=SUM(A1:A2)") == "'=SUM(A1:A2)"
    assert safe_csv_cell("Normal title") == "Normal title"
