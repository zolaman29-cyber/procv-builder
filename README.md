# ProCV Builder

A Django application for creating and privately saving career documents, editing a live résumé preview, and exporting selectable-text PDF files. The development setup uses SQLite; PostgreSQL can be selected with `DATABASE_URL`.

## Requirements

- Python 3.10 or later
- pip
- PostgreSQL only if using a PostgreSQL database

## Run locally

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
py manage.py migrate
py manage.py createsuperuser
py manage.py runserver
```

Open `http://127.0.0.1:8000/` and register an account. The Django admin is at `/admin/`.

## Configuration

Copy `.env.example` to `.env` and set environment variables in your shell or deployment environment. Django does not load `.env` automatically.

- `DJANGO_SECRET_KEY`: use a unique, randomly generated value.
- `DJANGO_DEBUG`: set to `0` in production.
- `DJANGO_ALLOWED_HOSTS`: comma-separated hostnames.
- `CSRF_TRUSTED_ORIGINS`: comma-separated origins including the scheme, such as `https://app.example.com`.
- `DATABASE_URL`: `sqlite:///db.sqlite3` or `postgresql://user:password@host:5432/database`.

When using PostgreSQL, create the database and its login role before running `migrate`. `psycopg` is included in the dependencies. For password reset in development, Django prints email to the runserver console; set `DJANGO_EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, and `DEFAULT_FROM_EMAIL` for your production mail provider.

## Features

- Django account registration (with a unique email address), login, and password reset with the framework's password hashing and password validators.
- Private, owner-scoped document listing, editing, duplication, and deletion.
- Six document categories and twelve selectable visual template treatments.
- Autosaving editor with a live preview, browser printing, and PDF download.
- Password reset through the configured email backend.
- Django admin for authorized staff; private document content is not registered in the admin.
- Staff-only site stats at `/admin/stats/`, including account and document totals plus daily page views, PDF downloads, and registrations.

The PDF exporter creates selectable text and paginates long documents. Printing uses the browser's print dialog and A4 print CSS. The current editor focuses on core résumé content (contact details, summary, experience, education, skills, projects, and certifications); photo cropping, custom sections, AI writing, and DOCX export are not included yet.

The site stats page is restricted to accounts with Django's `is_staff` permission. Create the first administrator with `python manage.py createsuperuser`, then sign in at `/admin/` and grant staff access to the intended account. Page views count successful HTML page loads, including reloads; they are not unique visitors. The app stores only daily aggregate counts and does not record visitor identities or IP addresses. PDF downloads count successful PDF exports.

## Production notes

## Deploy free on Render

This project includes a Render Blueprint in `render.yaml`. It configures a free Python web service, WhiteNoise static-file serving, production Gunicorn, migrations, HTTPS proxy handling, and a generated Django secret. The external PostgreSQL connection is intentionally supplied separately so the app never depends on Render's temporary local filesystem or an expiring free database.

1. Push this project to a GitHub repository. Do not include `.env`, `db.sqlite3`, `.venv`, or uploaded/private user data.
2. Create a free PostgreSQL project on [Neon](https://neon.com/), copy its connection string, and keep it private.
3. In [Render](https://render.com/), create a Blueprint from your GitHub repository and apply `render.yaml`.
4. When prompted for `DATABASE_URL`, paste the Neon connection string (including `sslmode=require`). Render will build the app and run database migrations.
5. When the first deployment is live, open the Render service Shell and run `python manage.py createsuperuser` to create the first administrator and access `/admin/stats/`.
6. Register a normal user at the deployed URL to start creating documents.

The free Render web service sleeps when idle and may take about a minute to wake. Neon free usage has limits, and free plans can change; review each provider's current limits. If password reset is needed online, configure SMTP variables in the Render service environment. Never put the database URL, secret key, or email credentials in source control.

The local SQLite database is never included in the Git repository. To migrate the existing accounts and documents after the hosted database is initialized, first confirm that the hosted app has no accounts/documents you need to keep. From this project directory, set `DATABASE_URL` in your local shell to the private Neon connection string, then run:

```powershell
$env:DATABASE_URL = "paste-your-private-Neon-connection-string-here"
.\.venv\Scripts\python.exe manage.py migrate_local_data --confirm
Remove-Item Env:DATABASE_URL
```

The command refuses to run without `--confirm` and refuses to write if the destination already has users or documents. It copies account password hashes and document data directly from the local SQLite file; the data is not exported into a fixture or committed. Keep the connection string private. Verify the hosted login and documents after it completes.

For any production deployment, use HTTPS, a strong secret key, a managed PostgreSQL database, and a production WSGI server. Back up the database regularly. Set `SECURE_HSTS_SECONDS` only after confirming the entire site (and any included subdomains) is permanently served over HTTPS. Do not use Django's development server in production.
