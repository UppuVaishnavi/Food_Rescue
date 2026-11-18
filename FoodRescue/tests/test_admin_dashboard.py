import os
import re
import sqlite3
import tempfile
import unittest

from app import create_app
from werkzeug.security import check_password_hash


class AdminDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = os.path.join(self.temp_dir.name, "foodrescue.sqlite3")
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "admin-dashboard-test-secret",
                "DATABASE": self.database_path,
            }
        )
        self.donor = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def csrf_token(self, client, path):
        response = client.get(path)
        self.assertEqual(response.status_code, 200)
        match = re.search(
            r'name="csrf_token" value="([^"]+)"',
            response.get_data(as_text=True),
        )
        self.assertIsNotNone(match)
        return match.group(1)

    def register_donor(self):
        token = self.csrf_token(self.donor, "/register")
        self.donor.post(
            "/register",
            data={
                "csrf_token": token,
                "name": "Fresh Foods",
                "email": "donor@example.com",
                "role": "donor",
                "password": "foodrescue123",
                "password_confirmation": "foodrescue123",
            },
        )
        token = self.csrf_token(self.donor, "/login")
        self.donor.post(
            "/login",
            data={
                "csrf_token": token,
                "email": "donor@example.com",
                "password": "foodrescue123",
            },
        )

    def create_listing(self):
        token = self.csrf_token(self.donor, "/donations/new")
        self.donor.post(
            "/donations/new",
            data={
                "csrf_token": token,
                "title": "Fresh apples",
                "category": "produce",
                "description": "A box of crisp apples, ready for pickup.",
                "quantity": "1 box",
                "pickup_location": "Subedari, Hanamkonda",
                "pickup_window": "Tomorrow, 2 PM to 5 PM",
            },
        )
        connection = sqlite3.connect(self.database_path)
        try:
            return connection.execute(
                "SELECT id FROM donations WHERE title = 'Fresh apples'"
            ).fetchone()[0]
        finally:
            connection.close()

    def create_admin_app(self, email="admin@example.com", password="secure-admin-passphrase"):
        return create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "admin-dashboard-test-secret",
                "DATABASE": self.database_path,
                "ADMIN_EMAIL": email,
                "ADMIN_PASSWORD": password,
                "ADMIN_NAME": "FoodRescue Admin",
            }
        )

    def login_admin(self, client, email="admin@example.com", password="secure-admin-passphrase"):
        token = self.csrf_token(client, "/login")
        return client.post(
            "/login",
            data={
                "csrf_token": token,
                "email": email,
                "password": password,
            },
            follow_redirects=True,
        )

    def test_environment_admin_can_review_and_remove_available_listings(self):
        self.register_donor()
        donation_id = self.create_listing()
        admin_app = self.create_admin_app()
        admin = admin_app.test_client()

        dashboard = self.login_admin(admin)
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b"Admin dashboard", dashboard.data)
        self.assertIn(b"donor@example.com", dashboard.data)

        token = self.csrf_token(admin, "/dashboard/admin")
        response = admin.post(
            f"/admin/donations/{donation_id}/cancel",
            data={"csrf_token": token},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"removed from available donations", response.data)

        connection = sqlite3.connect(self.database_path)
        try:
            status = connection.execute(
                "SELECT status FROM donations WHERE id = ?", (donation_id,)
            ).fetchone()[0]
            event = connection.execute(
                """
                SELECT event_type FROM donation_events
                WHERE donation_id = ? ORDER BY id DESC LIMIT 1
                """,
                (donation_id,),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(status, "cancelled")
        self.assertEqual(event, "admin_cancelled")

    def test_configured_existing_user_is_promoted_without_password_reset(self):
        token = self.csrf_token(self.donor, "/register")
        response = self.donor.post(
            "/register",
            data={
                "csrf_token": token,
                "name": "Existing Admin",
                "email": "admin@example.com",
                "role": "recipient",
                "password": "existing-user-password",
                "password_confirmation": "existing-user-password",
            },
        )
        self.assertEqual(response.status_code, 302)

        self.create_admin_app()
        connection = sqlite3.connect(self.database_path)
        try:
            role, password_hash = connection.execute(
                "SELECT role, password_hash FROM users WHERE email = ?",
                ("admin@example.com",),
            ).fetchone()
        finally:
            connection.close()

        self.assertEqual(role, "admin")
        self.assertTrue(check_password_hash(password_hash, "existing-user-password"))
        self.assertFalse(check_password_hash(password_hash, "secure-admin-passphrase"))

    def test_public_registration_cannot_create_admin(self):
        token = self.csrf_token(self.donor, "/register")
        response = self.donor.post(
            "/register",
            data={
                "csrf_token": token,
                "name": "Public Admin",
                "email": "public-admin@example.com",
                "role": "admin",
                "password": "foodrescue123",
                "password_confirmation": "foodrescue123",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Choose a valid account type", response.data)


if __name__ == "__main__":
    unittest.main()
