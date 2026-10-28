import sqlite3
import tempfile
from copy import deepcopy
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from .models import DailySiteStat, Document
from .templates import TEMPLATES


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

    def test_only_staff_can_view_site_stats(self):
        stats_url = reverse("site_stats")
        self.assertEqual(self.client.get(stats_url).status_code, 302)

        self.client.force_login(self.other)
        self.assertEqual(self.client.get(stats_url).status_code, 302)

        self.owner.is_staff = True
        self.owner.save(update_fields=["is_staff"])
        self.client.force_login(self.owner)
        response = self.client.get(stats_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Site stats")
        self.assertContains(response, "not unique visitors")

    def test_only_staff_can_view_user_management_pages(self):
        list_url = reverse("user_list")
        detail_url = reverse("user_detail", args=[self.other.pk])
        self.assertEqual(self.client.get(list_url).status_code, 302)
        self.assertEqual(self.client.get(detail_url).status_code, 302)

        self.client.force_login(self.other)
        self.assertEqual(self.client.get(list_url).status_code, 302)
        self.assertEqual(self.client.get(detail_url).status_code, 302)

    def test_staff_can_search_users_and_view_document_metadata(self):
        self.document.content = {"name": "Private Name", "summary": "Private document content"}
        self.document.save(update_fields=["content"])
        self.owner.is_staff = True
        self.owner.save(update_fields=["is_staff"])
        self.client.force_login(self.owner)

        response = self.client.get(reverse("user_list"), {"q": "other", "status": "active"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "other")
        self.assertNotContains(response, "owner@example.com")

        response = self.client.get(reverse("user_detail", args=[self.owner.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Private CV")
        self.assertContains(response, "Document content is private")
        self.assertNotContains(response, "Private Name")
        self.assertNotContains(response, "Private document content")

    def test_staff_can_toggle_regular_user_status_only_with_post(self):
        self.owner.is_staff = True
        self.owner.save(update_fields=["is_staff"])
        self.client.force_login(self.owner)
        action_url = reverse("toggle_user_active", args=[self.other.pk])

        self.assertEqual(self.client.get(action_url).status_code, 405)
        response = self.client.post(action_url)
        self.assertRedirects(response, reverse("user_detail", args=[self.other.pk]))
        self.other.refresh_from_db()
        self.assertFalse(self.other.is_active)

        self.client.post(action_url)
        self.other.refresh_from_db()
        self.assertTrue(self.other.is_active)

    def test_staff_cannot_change_own_or_other_staff_status(self):
        self.owner.is_staff = True
        self.owner.save(update_fields=["is_staff"])
        self.other.is_staff = True
        self.other.save(update_fields=["is_staff"])
        self.client.force_login(self.owner)

        self.client.post(reverse("toggle_user_active", args=[self.owner.pk]))
        self.client.post(reverse("toggle_user_active", args=[self.other.pk]))

        self.owner.refresh_from_db()
        self.other.refresh_from_db()
        self.assertTrue(self.owner.is_active)
        self.assertTrue(self.other.is_active)

    def test_site_stats_summarize_users_documents_and_daily_activity(self):
        today = timezone.localdate()
        DailySiteStat.objects.create(
            date=today,
            page_views=12,
            pdf_downloads=3,
            registrations=1,
        )
        self.owner.is_staff = True
        self.owner.save(update_fields=["is_staff"])
        self.client.force_login(self.owner)

        response = self.client.get(reverse("site_stats"), {"days": "7"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_users"], 2)
        self.assertEqual(response.context["total_documents"], 1)
        self.assertEqual(response.context["totals"]["page_views"], 12)
        self.assertEqual(response.context["totals"]["pdf_downloads"], 3)
        self.assertEqual(response.context["totals"]["registrations"], 1)
        self.assertEqual(len(response.context["chart"]), 7)

    def test_successful_html_page_view_is_recorded_but_admin_page_is_excluded(self):
        self.client.get(reverse("login"))
        stats = DailySiteStat.objects.get(date=timezone.localdate())
        self.assertEqual(stats.page_views, 1)

        self.owner.is_staff = True
        self.owner.save(update_fields=["is_staff"])
        self.client.force_login(self.owner)
        self.client.get(reverse("site_stats"))
        stats.refresh_from_db()
        self.assertEqual(stats.page_views, 1)

    def test_user_cannot_open_another_users_document(self):
        self.client.force_login(self.other)
        for url_name in ("edit_document", "download_pdf"):
            response = self.client.get(reverse(url_name, args=[self.document.pk]))
            self.assertEqual(response.status_code, 404)
        self.assertFalse(DailySiteStat.objects.filter(pdf_downloads__gt=0).exists())

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
        self.assertEqual(DailySiteStat.objects.get(date=timezone.localdate()).pdf_downloads, 1)

    def test_pdf_export_uses_selected_template(self):
        self.client.force_login(self.owner)
        templates = set()
        for template in TEMPLATES:
            self.document.template = template
            self.document.save(update_fields=["template"])
            response = self.client.get(reverse("download_pdf", args=[self.document.pk]))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.content.startswith(b"%PDF-"))
            templates.add(response.content)
        self.assertEqual(len(templates), len(TEMPLATES))

    def test_registration_creates_authenticated_user(self):
        response = self.client.post(reverse("register"), {
            "username": "new-person",
            "email": "new-person@example.com",
            "password1": "Long-valid-password-5421",
            "password2": "Long-valid-password-5421",
        })
        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(User.objects.get(username="new-person").email, "new-person@example.com")
        self.assertEqual(DailySiteStat.objects.get(date=timezone.localdate()).registrations, 1)

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
