# FoodRescue – Food Donation and Surplus Food Management System

FoodRescue is a Flask app for sharing surplus food, coordinating pickups, and tracking donations. SQLite is the default database; MySQL is available through environment configuration.

## Requirements
- Python 3.9 or newer
- VS Code
- Internet connection for Bootstrap, Google Fonts, the homepage image, and donation photos

## Run in VS Code

1. Extract the `FoodRescue` folder.
2. Open the folder in VS Code (`File` → `Open Folder`).
3. Open the VS Code terminal (`Terminal` → `New Terminal`).
4. Create and activate a virtual environment (recommended):

   **Windows PowerShell**
   ```powershell
   py -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

   If PowerShell blocks activation, use Command Prompt:
   ```bat
   py -m venv venv
   venv\Scripts\activate.bat
   ```

5. Install dependencies:
   ```bash
   python -m pip install -r requirements.txt
   ```

6. Start the website locally:
   ```bash
   python app.py
   ```

7. Open http://127.0.0.1:5000 in your browser.

Stop the server with `Ctrl+C` in the terminal.

## Deployment-ready setup

This project includes a production WSGI entry point and a `Procfile` for hosting providers such as Render, Railway, or Heroku.

- App entry: `app.py`
- Production server: `gunicorn`
- Windows-friendly local production test: `waitress`
- WSGI file: `wsgi.py`
- Startup command: `gunicorn app:app`

For deployment, set the app to listen on the platform-provided port via the `PORT` environment variable. The app reads `PORT` automatically when started in production mode. On Windows, you can test production behavior with: `python -m waitress --listen=0.0.0.0:5000 app:app`

## Features
- Register as a food donor, NGO/recipient, or volunteer.
- Donors can publish and cancel food listings.
- Recipients and volunteers can claim available listings and mark pickups as collected.
- Separate donor, recipient/volunteer, and admin dashboards are available. `/account` redirects each signed-in user to the correct dashboard.
- Donation tracking records listing creation, claims, collection, and cancellation. The donor, claimant, and admins can view a listing's timeline; other users cannot.
- The admin dashboard shows donation metrics and recent users/listings, and admins can remove available listings.
- Donor and collector email addresses are shown to each other only after a listing is claimed.
- Browse and filter donations by text and category.
- Five sample listings are seeded into the local database with food photos and Warangal/Hanamkonda pickup areas to demonstrate the complete claim/pickup flow. They are examples, not real food offers.

With the default SQLite backend, accounts and food listings are stored at `instance/foodrescue.sqlite3`. Passwords are hashed and login uses Flask sessions.

For production, set a long, unique `SECRET_KEY` environment variable and set `COOKIE_SECURE=1` when serving the app over HTTPS. If no key is configured, a local development key is generated in `instance/secret_key`. Set `DATABASE_PATH` to use a different SQLite file.

## Use MySQL instead of SQLite

Install and start a MySQL server, then create the database once:
```sql
CREATE DATABASE foodrescue CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

In PowerShell, configure the connection before starting the app:
```powershell
$env:DATABASE_BACKEND = "mysql"
$env:MYSQL_HOST = "127.0.0.1"
$env:MYSQL_PORT = "3306"
$env:MYSQL_DATABASE = "foodrescue"
$env:MYSQL_USER = "your-mysql-user"
$env:MYSQL_PASSWORD = "your-mysql-password"
python app.py
```

The app creates its MySQL tables and seeds the five sample listings at startup. The existing SQLite database is not changed or copied automatically; keep a backup and request a migration if you need to move its accounts and live donations. Do not put database credentials in source files or commit them. To return to SQLite, start the app with `DATABASE_BACKEND=sqlite` (or leave it unset).

## Configure the first admin

Set these environment variables before starting the app:

**Windows PowerShell**
```powershell
$env:ADMIN_EMAIL = "admin@example.com"
$env:ADMIN_PASSWORD = "use-a-unique-password-of-at-least-12-characters"
$env:ADMIN_NAME = "FoodRescue Admin"
python app.py
```

At startup, the app creates an admin account if that email is not registered. If the email already belongs to an account, the app promotes it to admin without changing its existing password. Admin accounts cannot be created through public registration. Keep the environment password private; it is only needed when creating a new admin account.

Email verification, password reset, social login, and financial contributions are not implemented. Contributions currently mean sharing surplus food.

Run the account and food-workflow tests with:
```bash
python -m unittest discover -s tests
```
