import os
import tempfile
import unittest

from app import create_app


class DonationsPageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret-key",
                "DATABASE": os.path.join(self.temp_dir.name, "users.sqlite3"),
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_donations_page_renders_five_sample_cards_and_claim_controls(self):
        response = self.client.get("/donations")
        page = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(page.count('class="col-md-6 col-xl-4 donation-item"'), 5)
        self.assertIn('id="donationSearch"', page)
        self.assertIn('id="donationCategory"', page)
        self.assertIn('src="/static/js/donations.js"', page)
        self.assertIn("5 sample listings are included", page)
        self.assertIn("Log in to claim", page)
        self.assertEqual(page.count('class="donation-photo"'), 5)
        self.assertIn("Hanamkonda", page)
        self.assertIn("Warangal Fort Road", page)


if __name__ == "__main__":
    unittest.main()
