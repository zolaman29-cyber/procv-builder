import sqlite3
import tempfile
from copy import deepcopy
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from .models import Document


class DocumentAccessTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="Valid-pass-5321")
        self.other = User.objects.create_user(username="other", password="Valid-pass-5321")
        self.document = Document.objects.create(
            owner=self.owner,
            title="Private CV",
            content={"name": "Private Person", "skills": ["Research"]},
        )

    def test_documents_require_login(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_user_cannot_open_another_users_document(self):
        self.client.force_login(self.other)
        for url_name in ("edit_document", "download_pdf"):
            response = self.client.get(reverse(url_name, args=[self.document.pk]))
            self.assertEqual(response.status_code, 404)

    def test_owner_can_save_document_content_and_template(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("save_document", args=[self.document.pk]),
            data='{"title":"Updated CV","template":"modern","content":{"name":"Jordan","skills":["Python"]}}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.document.refresh_from_db()
        self.assertEqual(self.document.title, "Updated CV")
        self.assertEqual(self.document.template, "modern")
        self.assertEqual(self.document.content["name"], "Jordan")

    def test_invalid_template_does_not_save(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("save_document", args=[self.document.pk]),
            data='{"title":"Updated CV","template":"not-a-template","content":{}}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.document.refresh_from_db()
        self.assertEqual(self.document.title, "Private CV")

    def test_pdf_export_contains_pdf_bytes(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("download_pdf", args=[self.document.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF-"))

    def test_registration_creates_authenticated_user(self):
        response = self.client.post(reverse("register"), {
            "username": "new-person",
            "email": "new-person@example.com",
            "password1": "Long-valid-password-5421",
            "password2": "Long-valid-password-5421",
        })
        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(User.objects.get(username="new-person").email, "new-person@example.com")

    def test_password_reset_form_is_available(self):
        response = self.client.get(reverse("password_reset"))
        self.assertEqual(response.status_code, 200)

    def test_document_creation_and_delete_are_owner_scoped(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("create_document"), {"kind": "resume", "title": "Product résumé"})
        self.assertEqual(response.status_code, 302)
        created = Document.objects.get(owner=self.owner, title="Product résumé")

        self.client.force_login(self.other)
        response = self.client.post(reverse("delete_document", args=[created.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Document.objects.filter(pk=created.pk).exists())

    def test_new_documents_do_not_share_nested_content(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("create_document"), {"kind": "resume", "title": "First draft"})
        self.assertEqual(response.status_code, 302)
        first = Document.objects.get(owner=self.owner, title="First draft")
        response = self.client.post(reverse("create_document"), {"kind": "resume", "title": "Second draft"})
        self.assertEqual(response.status_code, 302)
        second = Document.objects.get(owner=self.owner, title="Second draft")
        first.content["skills"].append("Python")
        first.save(update_fields=["content", "updated_at"])
        self.assertEqual(second.content["skills"], [])

    def test_duplicate_document_copies_nested_content_without_sharing_reference(self):
        self.client.force_login(self.owner)
        original = Document.objects.create(
            owner=self.owner,
            title="Original document",
            content={"name": "Jordan", "skills": ["Python"], "experience": [{"title": "Engineer"}]},
        )

        response = self.client.post(reverse("duplicate_document", args=[original.pk]))
        self.assertEqual(response.status_code, 302)

        duplicate = Document.objects.get(owner=self.owner, title="Original document (copy)")
        self.assertEqual(duplicate.content["name"], "Jordan")
        self.assertEqual(duplicate.content["skills"], ["Python"])
        self.assertIsNot(duplicate.content, original.content)
        duplicate.content["skills"].append("Django")
        duplicate.save(update_fields=["content", "updated_at"])
        self.assertEqual(original.content["skills"], ["Python"])

    def test_local_data_migration_requires_confirmation_and_empty_destination(self):
        with self.assertRaisesMessage(CommandError, "Pass --confirm"):
            call_command("migrate_local_data")
        with self.assertRaisesMessage(CommandError, "Destination already contains"):
            call_command("migrate_local_data", confirm=True)


class LocalDataMigrationTests(TransactionTestCase):
    def test_migration_copies_users_documents_and_timestamps(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "source.sqlite3"
            source = sqlite3.connect(source_path)
            source.executescript("""
                CREATE TABLE auth_user (
                    id INTEGER PRIMARY KEY, password TEXT, last_login TEXT,
                    is_superuser INTEGER, username TEXT, first_name TEXT,
                    last_name TEXT, email TEXT, is_staff INTEGER, is_active INTEGER,
                    date_joined TEXT
                );
                CREATE TABLE builder_document (
                    id INTEGER PRIMARY KEY, title TEXT, kind TEXT, template TEXT,
                    content TEXT, created_at TEXT, updated_at TEXT, owner_id INTEGER
                );
            """)
            source.execute(
                "INSERT INTO auth_user VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (7, "stored-password-hash", None, 0, "imported", "", "", "imported@example.com",
                 0, 1, "2025-01-02 03:04:05+00:00"),
            )
            source.execute(
                "INSERT INTO builder_document VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (11, "Imported CV", "cv", "classic", '{"name":"Imported User"}',
                 "2025-02-03 04:05:06+00:00", "2025-02-04 05:06:07+00:00", 7),
            )
            source.commit()
            source.close()

            call_command("migrate_local_data", confirm=True, source=str(source_path), verbosity=0)

        imported_user = User.objects.get(username="imported")
        imported_document = Document.objects.get(title="Imported CV")
        self.assertEqual(imported_user.password, "stored-password-hash")
        self.assertEqual(imported_document.owner_id, imported_user.pk)
        self.assertEqual(imported_document.content["name"], "Imported User")
        self.assertEqual(imported_document.created_at.isoformat(), "2025-02-03T04:05:06+00:00")
        self.assertEqual(imported_document.updated_at.isoformat(), "2025-02-04T05:06:07+00:00")
