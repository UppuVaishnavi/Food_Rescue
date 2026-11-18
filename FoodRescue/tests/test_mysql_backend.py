import os
import tempfile
import unittest

from app import MySQLConnection, create_app


class MySQLBackendTests(unittest.TestCase):
    def test_mysql_backend_requires_a_database_user(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(RuntimeError, "MYSQL_USER"):
                create_app(
                    {
                        "TESTING": True,
                        "SECRET_KEY": "mysql-config-test-secret",
                        "DATABASE": os.path.join(temp_dir, "unused.sqlite3"),
                        "DATABASE_BACKEND": "mysql",
                        "MYSQL_USER": "",
                    }
                )

    def test_connection_adapter_translates_parameter_placeholders(self):
        class FakeCursor:
            def execute(self, query, parameters):
                self.query = query
                self.parameters = parameters

        class FakeConnection:
            def __init__(self):
                self.cursor_result = FakeCursor()

            def cursor(self):
                return self.cursor_result

        connection = FakeConnection()
        database = MySQLConnection(connection)
        database.execute(
            "SELECT id FROM users WHERE email = ? AND role = ?",
            ("person@example.com", "donor"),
        )

        self.assertEqual(
            connection.cursor_result.query,
            "SELECT id FROM users WHERE email = %s AND role = %s",
        )
        self.assertEqual(
            connection.cursor_result.parameters,
            ("person@example.com", "donor"),
        )


if __name__ == "__main__":
    unittest.main()
