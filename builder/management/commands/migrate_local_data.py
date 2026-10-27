import json
import sqlite3
from datetime import datetime

from django.contrib.auth import get_user_model
from django.core.management.color import no_style
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from builder.models import Document


class Command(BaseCommand):
    help = "Copy local SQLite accounts and documents into the configured database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Confirm copying private local account and document data.",
        )
        parser.add_argument(
            "--source",
            default="db.sqlite3",
            help="Path to the local SQLite database (default: db.sqlite3).",
        )

    def handle(self, *args, **options):
        if not options["confirm"]:
            raise CommandError("Pass --confirm only after verifying the destination database.")

        source_path = options["source"]
        try:
            source = sqlite3.connect(source_path)
            source.row_factory = sqlite3.Row
        except sqlite3.Error as error:
            raise CommandError(f"Could not open local SQLite database: {error}") from error

        user_model = get_user_model()
        if user_model.objects.exists() or Document.objects.exists():
            source.close()
            raise CommandError(
                "Destination already contains users or documents. Migration stopped without changes."
            )

        try:
            users = source.execute(
                "SELECT id, password, last_login, is_superuser, username, "
                "first_name, last_name, email, is_staff, is_active, date_joined "
                "FROM auth_user ORDER BY id"
            ).fetchall()
            documents = source.execute(
                "SELECT id, title, kind, template, content, created_at, updated_at, owner_id "
                "FROM builder_document ORDER BY id"
            ).fetchall()
        except sqlite3.Error as error:
            source.close()
            raise CommandError(f"Could not read local accounts/documents: {error}") from error
        finally:
            source.close()

        with transaction.atomic():
            for row in users:
                user = user_model(
                    id=row["id"],
                    password=row["password"],
                    last_login=parse_datetime(row["last_login"]),
                    is_superuser=bool(row["is_superuser"]),
                    username=row["username"],
                    first_name=row["first_name"],
                    last_name=row["last_name"],
                    email=row["email"],
                    is_staff=bool(row["is_staff"]),
                    is_active=bool(row["is_active"]),
                    date_joined=parse_datetime(row["date_joined"]),
                )
                user.save(force_insert=True)

            imported_documents = [
                Document(
                    id=row["id"],
                    owner_id=row["owner_id"],
                    title=row["title"],
                    kind=row["kind"],
                    template=row["template"],
                    content=json.loads(row["content"] or "{}"),
                    created_at=parse_datetime(row["created_at"]),
                    updated_at=parse_datetime(row["updated_at"]),
                )
                for row in documents
            ]
            document_timestamps = [
                (document.pk, document.created_at, document.updated_at)
                for document in imported_documents
            ]
            Document.objects.bulk_create(imported_documents)
            for document_id, created_at, updated_at in document_timestamps:
                Document.objects.filter(pk=document_id).update(
                    created_at=created_at,
                    updated_at=updated_at,
                )

            reset_sql = connection.ops.sequence_reset_sql(no_style(), [user_model, Document])
            with connection.cursor() as cursor:
                for statement in reset_sql:
                    cursor.execute(statement)

        self.stdout.write(self.style.SUCCESS(
            f"Copied {len(users)} account(s) and {len(documents)} document(s)."
        ))


def parse_datetime(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed
