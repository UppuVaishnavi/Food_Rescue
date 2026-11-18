import hmac
import os
import secrets
import sqlite3
from datetime import timedelta
from functools import wraps

import pymysql
from pymysql.err import IntegrityError as MySQLIntegrityError
from flask import (
    Flask,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


DATABASE_INTEGRITY_ERRORS = (sqlite3.IntegrityError, MySQLIntegrityError)
ROLE_LABELS = {
    "donor": "Food donor",
    "recipient": "NGO / food recipient",
    "volunteer": "Volunteer",
}
ROLE_DISPLAY_LABELS = {**ROLE_LABELS, "admin": "Administrator"}
CATEGORIES = {
    "produce": "Fresh produce",
    "prepared": "Prepared meals",
    "bakery": "Bakery",
    "pantry": "Pantry",
    "other": "Other",
}
FOOD_IMAGES = {
    "produce": "https://images.unsplash.com/photo-1540420773420-3366772f4999?auto=format&fit=crop&w=900&q=85",
    "prepared": "https://images.unsplash.com/photo-1547592180-85f173990554?auto=format&fit=crop&w=900&q=85",
    "bakery": "https://images.unsplash.com/photo-1509440159596-0249088772ff?auto=format&fit=crop&w=900&q=85",
    "pantry": "https://images.unsplash.com/photo-1547592166-23ac45744acd?auto=format&fit=crop&w=900&q=85",
    "other": "https://images.unsplash.com/photo-1512621776951-a57141f2eefd?auto=format&fit=crop&w=900&q=85",
}
SAMPLE_DONATIONS = [
    (
        "Green Valley Market",
        "Seasonal produce boxes",
        "produce",
        "A sample selection of seasonal vegetables and fruit.",
        "18 boxes",
        "Subedari, Hanamkonda",
        "Weekdays, 2:00–5:00 PM",
        FOOD_IMAGES["produce"],
    ),
    (
        "Community Table Kitchen",
        "Fresh vegetarian lunch packs",
        "prepared",
        "Freshly prepared vegetarian lunch packs with rice and vegetables.",
        "30 servings",
        "Hanamkonda Chowrasta, Hanamkonda",
        "Daily, 1:00–3:00 PM",
        FOOD_IMAGES["prepared"],
    ),
    (
        "Sunrise Bakery",
        "Assorted breads and pastries",
        "bakery",
        "An end-of-day bakery assortment packed in collection bags.",
        "12 bags",
        "Kazipet Railway Station area",
        "Daily, 5:00–7:00 PM",
        FOOD_IMAGES["bakery"],
    ),
    (
        "Neighborhood Food Collective",
        "Canned goods and grains",
        "pantry",
        "A pantry bundle with canned goods and shelf-stable grains.",
        "24 grocery bags",
        "Warangal Fort Road, Warangal",
        "Weekdays, 10:00 AM–1:00 PM",
        FOOD_IMAGES["pantry"],
    ),
    (
        "Harvest Corner Cafe",
        "Fresh soup and rolls",
        "prepared",
        "A sample batch of vegetable soup and fresh rolls for sharing.",
        "16 meal sets",
        "Nakkalagutta, Hanamkonda",
        "Daily, 4:00–6:00 PM",
        FOOD_IMAGES["other"],
    ),
]


class MySQLConnection:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, query, parameters=()):
        cursor = self.connection.cursor()
        cursor.execute(query.replace("?", "%s"), parameters)
        return cursor

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


def _load_secret_key(instance_path):
    secret_key = os.environ.get("SECRET_KEY")
    if secret_key:
        return secret_key

    os.makedirs(instance_path, exist_ok=True)
    secret_path = os.path.join(instance_path, "secret_key")
    try:
        with open(secret_path, "x", encoding="utf-8") as secret_file:
            secret_file.write(secrets.token_hex(32))
    except FileExistsError:
        pass

    with open(secret_path, "r", encoding="utf-8") as secret_file:
        return secret_file.read()


def get_db():
    if "db" not in g:
        if current_app.config["DATABASE_BACKEND"] == "mysql":
            missing_settings = [
                setting
                for setting in ("MYSQL_HOST", "MYSQL_DATABASE", "MYSQL_USER")
                if not current_app.config[setting]
            ]
            if missing_settings:
                raise RuntimeError(
                    "Missing MySQL configuration: " + ", ".join(missing_settings)
                )
            connection = pymysql.connect(
                host=current_app.config["MYSQL_HOST"],
                port=int(current_app.config["MYSQL_PORT"]),
                user=current_app.config["MYSQL_USER"],
                password=current_app.config["MYSQL_PASSWORD"],
                database=current_app.config["MYSQL_DATABASE"],
                charset="utf8mb4",
                autocommit=False,
                connect_timeout=5,
                cursorclass=pymysql.cursors.DictCursor,
            )
            g.db = MySQLConnection(connection)
        else:
            g.db = sqlite3.connect(current_app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_error=None):
    database = g.pop("db", None)
    if database is not None:
        database.close()


def table_columns(connection, table_name):
    if current_app.config["DATABASE_BACKEND"] == "mysql":
        rows = connection.execute(f"SHOW COLUMNS FROM `{table_name}`").fetchall()
        return {row["Field"] for row in rows}
    return {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def ensure_mysql_index(connection, table_name, index_name, columns):
    indexes = {
        row["Key_name"]
        for row in connection.execute(f"SHOW INDEX FROM `{table_name}`").fetchall()
    }
    if index_name not in indexes:
        connection.execute(
            f"CREATE INDEX `{index_name}` ON `{table_name}` ({columns})"
        )


def seed_sample_donations(connection):
    existing_sample_titles = {
        row["title"]
        for row in connection.execute(
            "SELECT title FROM donations WHERE is_sample = 1"
        ).fetchall()
    }
    for sample in SAMPLE_DONATIONS:
        if sample[1] in existing_sample_titles:
            connection.execute(
                """
                UPDATE donations
                SET donor_name = ?, category = ?, description = ?, quantity = ?,
                    pickup_location = ?, pickup_window = ?, image_url = ?
                WHERE title = ? AND is_sample = 1
                """,
                (
                    sample[0],
                    sample[2],
                    sample[3],
                    sample[4],
                    sample[5],
                    sample[6],
                    sample[7],
                    sample[1],
                ),
            )
        else:
            connection.execute(
                """
                INSERT INTO donations (
                    donor_name, title, category, description, quantity,
                    pickup_location, pickup_window, image_url, is_sample
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                sample,
            )

    donations_without_history = connection.execute(
        """
        SELECT d.*
        FROM donations AS d
        WHERE NOT EXISTS (
            SELECT 1 FROM donation_events AS e WHERE e.donation_id = d.id
        )
        """
    ).fetchall()
    for donation in donations_without_history:
        creation_note = (
            "Sample listing added for demonstration."
            if donation["is_sample"]
            else "Food listing shared by the donor."
        )
        connection.execute(
            """
            INSERT INTO donation_events (
                donation_id, actor_id, event_type, note, created_at
            )
            VALUES (?, ?, 'created', ?, ?)
            """,
            (
                donation["id"],
                donation["donor_id"],
                creation_note,
                donation["created_at"],
            ),
        )
        if donation["status"] in ("claimed", "collected") and donation["collector_id"]:
            connection.execute(
                """
                INSERT INTO donation_events (
                    donation_id, actor_id, event_type, note, created_at
                )
                VALUES (?, ?, 'claimed', ?, ?)
                """,
                (
                    donation["id"],
                    donation["collector_id"],
                    "Food claimed; contact the donor to arrange pickup.",
                    donation["claimed_at"] or donation["created_at"],
                ),
            )
        if donation["status"] == "collected":
            connection.execute(
                """
                INSERT INTO donation_events (
                    donation_id, actor_id, event_type, note, created_at
                )
                VALUES (?, ?, 'collected', ?, ?)
                """,
                (
                    donation["id"],
                    donation["collector_id"],
                    "Pickup was marked as collected.",
                    donation["collected_at"] or donation["created_at"],
                ),
            )
        elif donation["status"] == "cancelled":
            connection.execute(
                """
                INSERT INTO donation_events (
                    donation_id, actor_id, event_type, note, created_at
                )
                VALUES (?, ?, 'cancelled', ?, ?)
                """,
                (
                    donation["id"],
                    donation["donor_id"],
                    "Listing was cancelled.",
                    donation["created_at"],
                ),
            )


def init_db():
    if current_app.config["DATABASE_BACKEND"] == "mysql":
        init_mysql_db()
        return

    database_path = current_app.config["DATABASE"]
    os.makedirs(os.path.dirname(os.path.abspath(database_path)), exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'recipient',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        user_columns = table_columns(connection, "users")
        if "role" not in user_columns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'recipient'"
            )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS donations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                donor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                donor_name TEXT NOT NULL,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                quantity TEXT NOT NULL,
                pickup_location TEXT NOT NULL,
                pickup_window TEXT NOT NULL,
                image_url TEXT,
                status TEXT NOT NULL DEFAULT 'available'
                    CHECK (status IN ('available', 'claimed', 'collected', 'cancelled')),
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
            CREATE TABLE IF NOT EXISTS donation_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                donation_id INTEGER NOT NULL
                    REFERENCES donations(id) ON DELETE CASCADE,
                actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                event_type TEXT NOT NULL
                    CHECK (event_type IN (
                        'created', 'claimed', 'collected', 'cancelled', 'admin_cancelled'
                    )),
                note TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        donation_columns = table_columns(connection, "donations")
        if "image_url" not in donation_columns:
            connection.execute("ALTER TABLE donations ADD COLUMN image_url TEXT")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_donations_status ON donations(status)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_donations_donor ON donations(donor_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_donation_events_donation "
            "ON donation_events(donation_id, created_at)"
        )

        seed_sample_donations(connection)
        connection.commit()
    finally:
        connection.close()


def init_mysql_db():
    connection = get_db()
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(254) CHARACTER SET utf8mb4
                    COLLATE utf8mb4_unicode_ci NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                role VARCHAR(20) NOT NULL DEFAULT 'recipient',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        if "role" not in table_columns(connection, "users"):
            connection.execute(
                "ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'recipient'"
            )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS donations (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                donor_id INT NULL,
                donor_name VARCHAR(100) NOT NULL,
                title VARCHAR(120) NOT NULL,
                category VARCHAR(20) NOT NULL,
                description TEXT NOT NULL,
                quantity VARCHAR(80) NOT NULL,
                pickup_location VARCHAR(160) NOT NULL,
                pickup_window VARCHAR(120) NOT NULL,
                image_url TEXT,
                status VARCHAR(20) NOT NULL DEFAULT 'available',
                collector_id INT NULL,
                is_sample TINYINT NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                claimed_at DATETIME NULL,
                collected_at DATETIME NULL,
                CONSTRAINT fk_donations_donor
                    FOREIGN KEY (donor_id) REFERENCES users(id) ON DELETE SET NULL,
                CONSTRAINT fk_donations_collector
                    FOREIGN KEY (collector_id) REFERENCES users(id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        if "image_url" not in table_columns(connection, "donations"):
            connection.execute("ALTER TABLE donations ADD COLUMN image_url TEXT")

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS donation_events (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                donation_id INT NOT NULL,
                actor_id INT NULL,
                event_type VARCHAR(30) NOT NULL,
                note TEXT NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_donation_events_donation
                    FOREIGN KEY (donation_id) REFERENCES donations(id) ON DELETE CASCADE,
                CONSTRAINT fk_donation_events_actor
                    FOREIGN KEY (actor_id) REFERENCES users(id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        ensure_mysql_index(
            connection, "donations", "idx_donations_status", "status"
        )
        ensure_mysql_index(connection, "donations", "idx_donations_donor", "donor_id")
        ensure_mysql_index(
            connection,
            "donation_events",
            "idx_donation_events_donation",
            "donation_id, created_at",
        )
        seed_sample_donations(connection)
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def provision_admin_account():
    email = current_app.config["ADMIN_EMAIL"].strip().lower()
    password = current_app.config["ADMIN_PASSWORD"]
    if not email:
        if password:
            raise RuntimeError("Set ADMIN_EMAIL when ADMIN_PASSWORD is configured.")
        return
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        raise RuntimeError("ADMIN_EMAIL must be a valid email address.")

    user = get_db().execute(
        "SELECT id FROM users WHERE email = ?",
        (email,),
    ).fetchone()
    if user is not None:
        get_db().execute("UPDATE users SET role = 'admin' WHERE id = ?", (user["id"],))
        get_db().commit()
        return
    if len(password) < 12:
        raise RuntimeError(
            "ADMIN_PASSWORD must be at least 12 characters to create the first admin."
        )

    name = current_app.config["ADMIN_NAME"].strip() or "FoodRescue Admin"
    if len(name) > 100:
        raise RuntimeError("ADMIN_NAME must be 100 characters or fewer.")
    get_db().execute(
        """
        INSERT INTO users (name, email, password_hash, role)
        VALUES (?, ?, ?, 'admin')
        """,
        (name, email, generate_password_hash(password)),
    )
    get_db().commit()


def record_donation_event(donation_id, actor_id, event_type, note):
    get_db().execute(
        """
        INSERT INTO donation_events (donation_id, actor_id, event_type, note)
        VALUES (?, ?, ?, ?)
        """,
        (donation_id, actor_id, event_type, note),
    )


def csrf_token():
    token = session.get("_csrf_token")
    if token is None:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def get_current_user():
    user_id = session.get("user_id")
    if user_id is None:
        return None
    return get_db().execute(
        "SELECT id, name, email, role FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        user = get_current_user()
        if user is None:
            session.clear()
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


def roles_required(*allowed_roles):
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            user = get_current_user()
            if user is None:
                session.clear()
                flash("Please log in to continue.", "warning")
                return redirect(url_for("login"))
            if user["role"] not in allowed_roles:
                abort(403, description="Your account type cannot perform this action.")
            return view(*args, **kwargs)

        return wrapped_view

    return decorator


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=_load_secret_key(app.instance_path),
        DATABASE_BACKEND=os.environ.get("DATABASE_BACKEND", "sqlite").strip().lower(),
        DATABASE=os.environ.get(
            "DATABASE_PATH", os.path.join(app.instance_path, "foodrescue.sqlite3")
        ),
        MYSQL_HOST=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        MYSQL_PORT=os.environ.get("MYSQL_PORT", "3306"),
        MYSQL_DATABASE=os.environ.get("MYSQL_DATABASE", "foodrescue"),
        MYSQL_USER=os.environ.get("MYSQL_USER", ""),
        MYSQL_PASSWORD=os.environ.get("MYSQL_PASSWORD", ""),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "").lower()
        in {"1", "true", "yes"},
        PERMANENT_SESSION_LIFETIME=timedelta(days=14),
        ADMIN_EMAIL=os.environ.get("ADMIN_EMAIL", "").strip().lower(),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", ""),
        ADMIN_NAME=os.environ.get("ADMIN_NAME", "FoodRescue Admin"),
    )
    if test_config is not None:
        app.config.update(test_config)
    if app.config["DATABASE_BACKEND"] not in {"sqlite", "mysql"}:
        raise RuntimeError("DATABASE_BACKEND must be either 'sqlite' or 'mysql'.")

    app.teardown_appcontext(close_db)
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.context_processor
    def inject_current_user():
        return {"current_user": get_current_user()}

    with app.app_context():
        init_db()
        provision_admin_account()

    @app.before_request
    def protect_post_requests():
        if request.method == "POST":
            submitted_token = request.form.get("csrf_token", "")
            expected_token = session.get("_csrf_token", "")
            if not submitted_token or not expected_token or not hmac.compare_digest(
                submitted_token, expected_token
            ):
                abort(400, description="The form expired. Please reload and try again.")

    @app.route("/")
    def home():
        return render_template("index.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if get_current_user() is not None:
            return redirect(url_for("account"))

        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            if not email or not password:
                flash("Enter your email address and password.", "danger")
                return render_template("login.html"), 400

            user = get_db().execute(
                "SELECT id, password_hash FROM users WHERE email = ?",
                (email,),
            ).fetchone()
            if user is None or not check_password_hash(user["password_hash"], password):
                flash("The email or password is incorrect.", "danger")
                return render_template("login.html"), 401

            session.clear()
            session["user_id"] = user["id"]
            session.permanent = request.form.get("remember_me") == "on"
            csrf_token()
            flash("You are now logged in.", "success")
            return redirect(url_for("account"))

        return render_template("login.html")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if get_current_user() is not None:
            return redirect(url_for("account"))

        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            password_confirmation = request.form.get("password_confirmation", "")
            role = request.form.get("role", "").strip()

            if not name or not email or not password or not role:
                flash("Complete all fields to create your account.", "danger")
            elif len(name) > 100 or len(email) > 254:
                flash("Your name or email address is too long.", "danger")
            elif "@" not in email or "." not in email.rsplit("@", 1)[-1]:
                flash("Enter a valid email address.", "danger")
            elif role not in ROLE_LABELS:
                flash("Choose a valid account type.", "danger")
            elif len(password) < 8:
                flash("Your password must be at least 8 characters.", "danger")
            elif password != password_confirmation:
                flash("The passwords do not match.", "danger")
            else:
                try:
                    get_db().execute(
                        """
                        INSERT INTO users (name, email, password_hash, role)
                        VALUES (?, ?, ?, ?)
                        """,
                        (name, email, generate_password_hash(password), role),
                    )
                    get_db().commit()
                except DATABASE_INTEGRITY_ERRORS:
                    flash("An account with that email already exists.", "danger")
                else:
                    flash("Account created. You can now log in.", "success")
                    return redirect(url_for("login"))

            return render_template(
                "register.html", roles=ROLE_LABELS, selected_role=role
            ), 400

        return render_template("register.html", roles=ROLE_LABELS, selected_role="")

    @app.route("/account")
    @login_required
    def account():
        user = get_current_user()
        dashboard_endpoints = {
            "donor": "donor_dashboard",
            "recipient": "recipient_dashboard",
            "volunteer": "recipient_dashboard",
            "admin": "admin_dashboard",
        }
        return redirect(url_for(dashboard_endpoints[user["role"]]))

    @app.route("/dashboard/donor")
    @roles_required("donor")
    def donor_dashboard():
        user = get_current_user()
        shared_donations = get_db().execute(
            """
            SELECT d.*, collector.name AS collector_name,
                   collector.email AS collector_email
            FROM donations AS d
            LEFT JOIN users AS collector ON collector.id = d.collector_id
            WHERE d.donor_id = ?
            ORDER BY d.id DESC
            """,
            (user["id"],),
        ).fetchall()
        stats = get_db().execute(
            """
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(CASE WHEN status = 'available' THEN 1 ELSE 0 END), 0)
                       AS available,
                   COALESCE(SUM(CASE WHEN status = 'claimed' THEN 1 ELSE 0 END), 0)
                       AS claimed,
                   COALESCE(SUM(CASE WHEN status = 'collected' THEN 1 ELSE 0 END), 0)
                       AS collected
            FROM donations
            WHERE donor_id = ?
            """,
            (user["id"],),
        ).fetchone()
        return render_template(
            "account.html",
            user=user,
            role_label=ROLE_DISPLAY_LABELS[user["role"]],
            categories=CATEGORIES,
            shared_donations=shared_donations,
            stats=stats,
        )

    @app.route("/dashboard/recipient")
    @roles_required("recipient", "volunteer")
    def recipient_dashboard():
        user = get_current_user()
        claimed_donations = get_db().execute(
            """
            SELECT d.*, donor.email AS donor_email
            FROM donations AS d
            LEFT JOIN users AS donor ON donor.id = d.donor_id
            WHERE d.collector_id = ?
            ORDER BY d.id DESC
            """,
            (user["id"],),
        ).fetchall()
        stats = get_db().execute(
            """
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(CASE WHEN status = 'claimed' THEN 1 ELSE 0 END), 0)
                       AS claimed,
                   COALESCE(SUM(CASE WHEN status = 'collected' THEN 1 ELSE 0 END), 0)
                       AS collected
            FROM donations
            WHERE collector_id = ?
            """,
            (user["id"],),
        ).fetchone()
        return render_template(
            "recipient_dashboard.html",
            user=user,
            role_label=ROLE_DISPLAY_LABELS[user["role"]],
            categories=CATEGORIES,
            claimed_donations=claimed_donations,
            stats=stats,
        )

    @app.route("/dashboard/admin")
    @roles_required("admin")
    def admin_dashboard():
        stats = get_db().execute(
            """
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(CASE WHEN status = 'available' THEN 1 ELSE 0 END), 0)
                       AS available,
                   COALESCE(SUM(CASE WHEN status = 'claimed' THEN 1 ELSE 0 END), 0)
                       AS claimed,
                   COALESCE(SUM(CASE WHEN status = 'collected' THEN 1 ELSE 0 END), 0)
                       AS collected,
                   COALESCE(SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END), 0)
                       AS cancelled
            FROM donations
            """
        ).fetchone()
        user_counts = get_db().execute(
            """
            SELECT role, COUNT(*) AS total
            FROM users
            GROUP BY role
            ORDER BY role
            """
        ).fetchall()
        users = get_db().execute(
            """
            SELECT id, name, email, role, created_at
            FROM users
            ORDER BY id DESC
            LIMIT 100
            """
        ).fetchall()
        donations = get_db().execute(
            """
            SELECT d.*, donor.email AS donor_email
            FROM donations AS d
            LEFT JOIN users AS donor ON donor.id = d.donor_id
            ORDER BY d.id DESC
            LIMIT 100
            """
        ).fetchall()
        return render_template(
            "admin_dashboard.html",
            stats=stats,
            user_counts=user_counts,
            users=users,
            donations=donations,
            categories=CATEGORIES,
        )

    @app.route("/donations/<int:donation_id>/tracking")
    @login_required
    def track_donation(donation_id):
        user = get_current_user()
        donation = get_db().execute(
            """
            SELECT d.*, donor.email AS donor_email,
                   collector.name AS collector_name,
                   collector.email AS collector_email
            FROM donations AS d
            LEFT JOIN users AS donor ON donor.id = d.donor_id
            LEFT JOIN users AS collector ON collector.id = d.collector_id
            WHERE d.id = ?
            """,
            (donation_id,),
        ).fetchone()
        if donation is None:
            abort(404)
        if user["role"] != "admin" and user["id"] not in (
            donation["donor_id"],
            donation["collector_id"],
        ):
            abort(403, description="Only the donor, claimant, or an admin can track this listing.")
        events = get_db().execute(
            """
            SELECT e.*, actor.name AS actor_name
            FROM donation_events AS e
            LEFT JOIN users AS actor ON actor.id = e.actor_id
            WHERE e.donation_id = ?
            ORDER BY e.created_at, e.id
            """,
            (donation_id,),
        ).fetchall()
        return render_template(
            "donation_tracking.html",
            donation=donation,
            events=events,
        )

    @app.route("/logout", methods=["POST"])
    @login_required
    def logout():
        session.clear()
        flash("You have been logged out.", "success")
        return redirect(url_for("login"))

    @app.route("/donations")
    def donations():
        user = get_current_user()
        query = """
            SELECT d.*
            FROM donations AS d
            WHERE d.status = 'available'
        """
        parameters = ()
        if user is not None and user["role"] == "donor":
            query += " AND (d.donor_id IS NULL OR d.donor_id != ?)"
            parameters = (user["id"],)
        query += " ORDER BY d.is_sample DESC, d.id DESC"
        listings = get_db().execute(query, parameters).fetchall()
        return render_template(
            "donations.html",
            donations=listings,
            categories=CATEGORIES,
            images=FOOD_IMAGES,
        )

    @app.route("/donations/new", methods=["GET", "POST"])
    @roles_required("donor")
    def create_donation():
        user = get_current_user()
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            category = request.form.get("category", "").strip()
            description = request.form.get("description", "").strip()
            quantity = request.form.get("quantity", "").strip()
            pickup_location = request.form.get("pickup_location", "").strip()
            pickup_window = request.form.get("pickup_window", "").strip()

            if not all(
                (title, category, description, quantity, pickup_location, pickup_window)
            ):
                flash("Complete all fields before sharing food.", "danger")
            elif category not in CATEGORIES:
                flash("Choose a valid food category.", "danger")
            elif (
                len(title) > 120
                or len(description) > 1200
                or len(quantity) > 80
                or len(pickup_location) > 160
                or len(pickup_window) > 120
            ):
                flash("One or more fields are too long.", "danger")
            else:
                result = get_db().execute(
                    """
                    INSERT INTO donations (
                        donor_id, donor_name, title, category, description,
                        quantity, pickup_location, pickup_window, image_url
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user["id"],
                        user["name"],
                        title,
                        category,
                        description,
                        quantity,
                        pickup_location,
                        pickup_window,
                        FOOD_IMAGES[category],
                    ),
                )
                record_donation_event(
                    result.lastrowid,
                    user["id"],
                    "created",
                    f"Food listing shared by {user['name']}.",
                )
                get_db().commit()
                flash("Your food listing is now available to the community.", "success")
                return redirect(url_for("account"))

            return render_template(
                "donation_form.html", categories=CATEGORIES, form_data=request.form
            ), 400

        return render_template("donation_form.html", categories=CATEGORIES, form_data={})

    @app.route("/donations/<int:donation_id>/claim", methods=["POST"])
    @roles_required("recipient", "volunteer")
    def claim_donation(donation_id):
        user = get_current_user()
        result = get_db().execute(
            """
            UPDATE donations
            SET status = 'claimed', collector_id = ?, claimed_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'available'
              AND (donor_id IS NULL OR donor_id != ?)
            """,
            (user["id"], donation_id, user["id"]),
        )
        if result.rowcount == 1:
            record_donation_event(
                donation_id,
                user["id"],
                "claimed",
                f"Food claimed by {user['name']}.",
            )
        get_db().commit()
        if result.rowcount == 1:
            flash(
                "Food claimed. Donor contact details are available in your account.",
                "success",
            )
            return redirect(url_for("account"))

        flash("This listing is no longer available to claim.", "warning")
        return redirect(url_for("donations"))

    @app.route("/donations/<int:donation_id>/collect", methods=["POST"])
    @roles_required("recipient", "volunteer")
    def mark_collected(donation_id):
        user = get_current_user()
        result = get_db().execute(
            """
            UPDATE donations
            SET status = 'collected', collected_at = CURRENT_TIMESTAMP
            WHERE id = ? AND collector_id = ? AND status = 'claimed'
            """,
            (donation_id, user["id"]),
        )
        if result.rowcount == 1:
            record_donation_event(
                donation_id,
                user["id"],
                "collected",
                f"Pickup marked as collected by {user['name']}.",
            )
        get_db().commit()
        if result.rowcount == 1:
            flash("Pickup marked as collected. Thank you for helping!", "success")
        else:
            flash("Only the person who claimed this food can mark it collected.", "warning")
        return redirect(url_for("account"))

    @app.route("/donations/<int:donation_id>/cancel", methods=["POST"])
    @roles_required("donor")
    def cancel_donation(donation_id):
        user = get_current_user()
        result = get_db().execute(
            """
            UPDATE donations
            SET status = 'cancelled'
            WHERE id = ? AND donor_id = ? AND status = 'available'
            """,
            (donation_id, user["id"]),
        )
        if result.rowcount == 1:
            record_donation_event(
                donation_id,
                user["id"],
                "cancelled",
                f"Listing cancelled by {user['name']}.",
            )
        get_db().commit()
        if result.rowcount == 1:
            flash("Your food listing has been cancelled.", "success")
        else:
            flash("This listing can no longer be cancelled.", "warning")
        return redirect(url_for("account"))

    @app.route("/admin/donations/<int:donation_id>/cancel", methods=["POST"])
    @roles_required("admin")
    def admin_cancel_donation(donation_id):
        user = get_current_user()
        result = get_db().execute(
            """
            UPDATE donations
            SET status = 'cancelled'
            WHERE id = ? AND status = 'available'
            """,
            (donation_id,),
        )
        if result.rowcount == 1:
            record_donation_event(
                donation_id,
                user["id"],
                "admin_cancelled",
                f"Listing removed by administrator {user['name']}.",
            )
        get_db().commit()
        if result.rowcount == 1:
            flash("The listing was removed from available donations.", "success")
        else:
            flash("Only available listings can be removed.", "warning")
        return redirect(url_for("admin_dashboard"))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
