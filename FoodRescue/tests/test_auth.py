import os
import re
import sqlite3
import tempfile
import unittest

from app import create_app
from werkzeug.security import check_password_hash


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = os.path.join(self.temp_dir.name, "users.sqlite3")
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret-key",
                "DATABASE": database_path,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def csrf_token(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        match = re.search(
            r'name="csrf_token" value="([^"]+)"',
            response.get_data(as_text=True),
        )
        self.assertIsNotNone(match)
        return match.group(1)

    def register_user(self, email="sam@example.com", password="foodrescue123"):
        token = self.csrf_token("/register")
        return self.client.post(
            "/register",
            data={
                "csrf_token": token,
                "name": "Sam Green",
                "email": email,
                "role": "recipient",
                "password": password,
                "password_confirmation": password,
            },
            follow_redirects=True,
        )

    def test_registration_hashes_password_and_login_opens_account(self):
        response = self.register_user(email="SAM@example.com")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Account created", response.data)

        connection = sqlite3.connect(self.app.config["DATABASE"])
        try:
            password_hash = connection.execute(
                "SELECT password_hash FROM users WHERE email = ?",
                ("sam@example.com",),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertNotEqual(password_hash, "foodrescue123")
        self.assertTrue(check_password_hash(password_hash, "foodrescue123"))

        token = self.csrf_token("/login")
        response = self.client.post(
            "/login",
            data={
                "csrf_token": token,
                "email": "sam@example.com",
                "password": "foodrescue123",
                "remember_me": "on",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Welcome, Sam Green", response.data)
        with self.client.session_transaction() as user_session:
            self.assertTrue(user_session.permanent)

    def test_invalid_credentials_do_not_log_in(self):
        self.register_user()
        token = self.csrf_token("/login")
        response = self.client.post(
            "/login",
            data={
                "csrf_token": token,
                "email": "sam@example.com",
                "password": "incorrect-password",
            },
        )
        self.assertEqual(response.status_code, 401)
        with self.client.session_transaction() as user_session:
            self.assertNotIn("user_id", user_session)

    def test_registration_rejects_duplicate_email_and_short_password(self):
        self.register_user()

        token = self.csrf_token("/register")
        response = self.client.post(
            "/register",
            data={
                "csrf_token": token,
                "name": "Another User",
                "email": "SAM@example.com",
                "role": "recipient",
                "password": "foodrescue123",
                "password_confirmation": "foodrescue123",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"already exists", response.data)

        token = self.csrf_token("/register")
        response = self.client.post(
            "/register",
            data={
                "csrf_token": token,
                "name": "Another User",
                "email": "another@example.com",
                "role": "recipient",
                "password": "short",
                "password_confirmation": "short",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"at least 8 characters", response.data)

    def test_post_without_csrf_token_is_rejected(self):
        response = self.client.post("/login", data={"email": "sam@example.com"})
        self.assertEqual(response.status_code, 400)

    def test_logout_clears_session(self):
        self.register_user()
        token = self.csrf_token("/login")
        self.client.post(
            "/login",
            data={
                "csrf_token": token,
                "email": "sam@example.com",
                "password": "foodrescue123",
            },
        )
        with self.client.session_transaction() as user_session:
            token = user_session["_csrf_token"]

        response = self.client.post(
            "/logout",
            data={"csrf_token": token},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as user_session:
            self.assertNotIn("user_id", user_session)
        self.assertIn(b"You have been logged out", response.data)


if __name__ == "__main__":
    unittest.main()
