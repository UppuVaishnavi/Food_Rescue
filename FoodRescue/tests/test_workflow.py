import os
import re
import sqlite3
import tempfile
import unittest

from app import create_app


class FoodWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = os.path.join(self.temp_dir.name, "foodrescue.sqlite3")
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "workflow-test-secret",
                "DATABASE": self.database_path,
            }
        )
        self.donor = self.app.test_client()
        self.recipient = self.app.test_client()

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

    def register_and_login(self, client, name, email, role):
        token = self.csrf_token(client, "/register")
        response = client.post(
            "/register",
            data={
                "csrf_token": token,
                "name": name,
                "email": email,
                "role": role,
                "password": "foodrescue123",
                "password_confirmation": "foodrescue123",
            },
        )
        self.assertEqual(response.status_code, 302)

        token = self.csrf_token(client, "/login")
        response = client.post(
            "/login",
            data={
                "csrf_token": token,
                "email": email,
                "password": "foodrescue123",
            },
        )
        self.assertEqual(response.status_code, 302)

    def create_live_listing(self):
        token = self.csrf_token(self.donor, "/donations/new")
        response = self.donor.post(
            "/donations/new",
            data={
                "csrf_token": token,
                "title": "Fresh apples",
                "category": "produce",
                "description": "A box of crisp apples, ready for pickup.",
                "quantity": "1 box",
                "pickup_location": "Northside Community Hub",
                "pickup_window": "Tomorrow, 2 PM to 5 PM",
            },
        )
        self.assertEqual(response.status_code, 302)

        connection = sqlite3.connect(self.database_path)
        try:
            return connection.execute(
                "SELECT id FROM donations WHERE title = ?",
                ("Fresh apples",),
            ).fetchone()[0]
        finally:
            connection.close()

    def test_donor_listing_claim_contact_and_collection_flow(self):
        self.register_and_login(
            self.donor, "Fresh Foods", "donor@example.com", "donor"
        )
        donation_id = self.create_live_listing()

        self.register_and_login(
            self.recipient, "Community Pantry", "pantry@example.com", "recipient"
        )
        donations_page = self.recipient.get("/donations")
        self.assertIn(b"Fresh apples", donations_page.data)
        self.assertNotIn(b"donor@example.com", donations_page.data)
        self.assertEqual(
            self.recipient.get(f"/donations/{donation_id}/tracking").status_code, 403
        )

        token = self.csrf_token(self.recipient, "/donations")
        response = self.recipient.post(
            f"/donations/{donation_id}/claim",
            data={"csrf_token": token},
        )
        self.assertEqual(response.status_code, 302)
        recipient_dashboard = self.recipient.get("/account", follow_redirects=True)
        self.assertIn(b"donor@example.com", recipient_dashboard.data)
        tracking_page = self.recipient.get(f"/donations/{donation_id}/tracking")
        self.assertEqual(tracking_page.status_code, 200)
        self.assertIn(b"Food listing shared by Fresh Foods", tracking_page.data)
        self.assertIn(b"Food claimed by Community Pantry", tracking_page.data)

        donor_dashboard = self.donor.get("/account", follow_redirects=True)
        self.assertIn(b"pantry@example.com", donor_dashboard.data)
        self.assertIn(b"Donor dashboard", donor_dashboard.data)

        token = self.csrf_token(self.recipient, "/dashboard/recipient")
        response = self.recipient.post(
            f"/donations/{donation_id}/collect",
            data={"csrf_token": token},
        )
        self.assertEqual(response.status_code, 302)
        donor_dashboard = self.donor.get("/account", follow_redirects=True)
        self.assertIn(b"Collected", donor_dashboard.data)
        tracking_page = self.recipient.get(f"/donations/{donation_id}/tracking")
        self.assertIn(b"Pickup marked as collected", tracking_page.data)

    def test_only_donors_can_publish_food(self):
        self.register_and_login(
            self.recipient, "Community Pantry", "pantry@example.com", "recipient"
        )
        response = self.recipient.get("/donations/new")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.recipient.get("/dashboard/admin").status_code, 403)

    def test_existing_accounts_are_migrated_and_samples_are_seeded(self):
        legacy_database = os.path.join(self.temp_dir.name, "legacy.sqlite3")
        connection = sqlite3.connect(legacy_database)
        try:
            connection.execute(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                ("Existing User", "existing@example.com", "old-hash"),
            )
            connection.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                ("Existing Recipient", "recipient@example.com", "old-hash"),
            )
            connection.execute(
                """
                CREATE TABLE donations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    donor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    donor_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL,
                    description TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    pickup_location TEXT NOT NULL,
                    pickup_window TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'available',
                    collector_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    is_sample INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    claimed_at TEXT,
                    collected_at TEXT
                )
                """
            )
            connection.execute(
                """
                INSERT INTO donations (
                    donor_id, donor_name, title, category, description, quantity,
                    pickup_location, pickup_window, status, collector_id, claimed_at
                )
                VALUES (1, 'Existing User', 'Legacy claimed food', 'produce',
                        'Food from before tracking was added.', '1 box',
                        'Subedari, Hanamkonda', 'Tomorrow afternoon', 'claimed', 2,
                        '2024-01-02 12:00:00')
                """
            )
            connection.commit()
        finally:
            connection.close()

        create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "migration-test-secret",
                "DATABASE": legacy_database,
            }
        )
        connection = sqlite3.connect(legacy_database)
        try:
            role = connection.execute(
                "SELECT role FROM users WHERE email = ?",
                ("existing@example.com",),
            ).fetchone()[0]
            sample_count = connection.execute(
                "SELECT COUNT(*) FROM donations WHERE is_sample = 1"
            ).fetchone()[0]
            sample_event_count = connection.execute(
                """
                SELECT COUNT(*) FROM donation_events AS e
                JOIN donations AS d ON d.id = e.donation_id
                WHERE d.is_sample = 1 AND e.event_type = 'created'
                """
            ).fetchone()[0]
            legacy_event_types = [
                row[0]
                for row in connection.execute(
                    """
                    SELECT event_type FROM donation_events AS e
                    JOIN donations AS d ON d.id = e.donation_id
                    WHERE d.title = 'Legacy claimed food'
                    ORDER BY e.id
                    """
                ).fetchall()
            ]
        finally:
            connection.close()

        self.assertEqual(role, "recipient")
        self.assertEqual(sample_count, 5)
        self.assertEqual(sample_event_count, 5)
        self.assertEqual(legacy_event_types, ["created", "claimed"])


if __name__ == "__main__":
    unittest.main()
