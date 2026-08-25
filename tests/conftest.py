import re
import sys
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app  # noqa: E402
from database import get_db  # noqa: E402


@pytest.fixture()
def app(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-key",
            "DATABASE": str(tmp_path / "test.sqlite"),
        }
    )

    with application.app_context():
        db = get_db()
        db.execute(
            """
            INSERT INTO users (full_name, student_id, email, password_hash, role)
            VALUES (?, NULL, ?, ?, 'admin')
            """,
            ("System Administrator", "admin@example.edu", generate_password_hash("AdminPass123")),
        )
        db.commit()

    yield application


@pytest.fixture()
def client(app):
    return app.test_client()


def csrf_token(client, path):
    response = client.get(path)
    match = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
    assert match, f"CSRF token not found at {path}"
    return match.group(1).decode()


@pytest.fixture()
def form_post(client):
    def submit(path, data, token_path=None, **kwargs):
        payload = dict(data)
        payload["csrf_token"] = csrf_token(client, token_path or path)
        return client.post(path, data=payload, **kwargs)

    return submit


@pytest.fixture()
def registered_student(form_post):
    response = form_post(
        "/register",
        {
            "full_name": "Test Student",
            "student_id": "STU-1001",
            "email": "student@example.edu",
            "password": "StudentPass123",
            "confirm_password": "StudentPass123",
        },
    )
    assert response.status_code == 302
    return {"email": "student@example.edu", "password": "StudentPass123"}
