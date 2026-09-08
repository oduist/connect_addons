# -*- coding: utf-8 -*-
import os
import tempfile
from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.connect_book.models.connect_book import MAX_DOC_BYTES


@tagged("post_install", "-at_install", "connect_book")
class TestConnectBook(TransactionCase):
    """The read path is exercised against a fake module directory on disk."""

    def setUp(self):
        super().setUp()
        self.book = self.env["connect.book"]
        # TransactionCase runs as the technical superuser (uid=1), a
        # different record from base.user_admin -- the one
        # connect/security/groups.xml actually grants
        # connect.group_connect_admin to. That user already has
        # base.group_system (see test_get_admin_book_allows_system_group);
        # grant it the Connect role too so get_book()/get_changes() behave
        # the same way for tests that call them directly on self.book.
        self.env.user.write({
            "group_ids": [(4, self.env.ref("connect.group_connect_admin").id)]
        })
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.module_path = self.tmp.name
        os.makedirs(os.path.join(self.module_path, "doc", "changes"))

    def _write(self, relpath, content):
        path = os.path.join(self.module_path, "doc", relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

    def _patch_path(self):
        """Point get_module_path() at the temporary module directory."""
        return patch(
            "odoo.addons.connect_book.models.connect_book.get_module_path",
            return_value=self.module_path,
        )

    def test_doc_lang_normalises_locale(self):
        self.assertEqual(
            self.book.with_context(lang="en_US")._doc_lang(), "en"
        )

    def test_doc_lang_rejects_path_traversal(self):
        self.assertEqual(
            self.book.with_context(lang="../../etc")._doc_lang(), "en"
        )

    def test_read_module_doc_prefers_translation(self):
        self._write("user_guide.md", "# Source\n")
        self._write("i18n/fr/user_guide.md", "<!-- i18n source=user_guide.md sha=abc lang=fr -->\n# Source FR\n")
        with self._patch_path():
            html = self.book._read_module_doc("connect", "user_guide.md", "fr")
        self.assertIn("Source FR", html)
        self.assertNotIn("i18n source=", html)

    def test_read_module_doc_falls_back_to_source(self):
        self._write("user_guide.md", "# Source\n")
        with self._patch_path():
            html = self.book._read_module_doc("connect", "user_guide.md", "de")
        self.assertIn("Source", html)

    def test_read_module_doc_missing_returns_none(self):
        with self._patch_path():
            self.assertIsNone(
                self.book._read_module_doc("connect", "admin_guide.md", "en")
            )

    def test_get_admin_book_requires_system_group(self):
        user = self.env["res.users"].create({
            "name": "Book Reader",
            "login": "book.reader@example.com",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        with self.assertRaises(AccessError):
            self.env["connect.book"].with_user(user).get_admin_book()

    def test_get_admin_book_allows_system_group(self):
        result = self.book.get_admin_book()   # test env user is a superuser
        self.assertIn("pages", result)

    def test_get_book_requires_connect_role(self):
        user = self.env["res.users"].create({
            "name": "No Connect Role",
            "login": "no.connect.role@example.com",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        with self.assertRaises(AccessError):
            self.env["connect.book"].with_user(user).get_book()

    def test_get_changes_requires_connect_role(self):
        user = self.env["res.users"].create({
            "name": "No Connect Role",
            "login": "no.connect.role.changes@example.com",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        with self.assertRaises(AccessError):
            self.env["connect.book"].with_user(user).get_changes()

    def test_get_book_allows_connect_user_group(self):
        user = self.env["res.users"].create({
            "name": "Connect User",
            "login": "connect.user.book@example.com",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("connect.group_connect_user").id,
            ])],
        })
        self._write("user_guide.md", "# Guide\n")
        with self._patch_path():
            result = self.env["connect.book"].with_user(user).get_book()
        self.assertIn("pages", result)

    def test_get_changes_allows_connect_user_group(self):
        user = self.env["res.users"].create({
            "name": "Connect User",
            "login": "connect.user.changes@example.com",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("connect.group_connect_user").id,
            ])],
        })
        self._write("changes/2026-08-13.md", "### Added\nsomething\n")
        with self._patch_path():
            result = self.env["connect.book"].with_user(user).get_changes()
        self.assertIn("days", result)

    def test_read_module_doc_skips_oversized_file(self):
        self._write("user_guide.md", "x" * (MAX_DOC_BYTES + 1))
        with self._patch_path():
            html = self.book._read_module_doc("connect", "user_guide.md", "en")
        self.assertIsNone(html)

    def test_render_doc_html_returns_none_on_render_failure(self):
        self._write("user_guide.md", "# Guide\n")
        filepath = os.path.join(self.module_path, "doc", "user_guide.md")
        with patch(
            "odoo.addons.connect_book.models.connect_book.md_to_html",
            side_effect=RuntimeError("boom"),
        ):
            html = self.book._render_doc_html(filepath, strip_marker=True)
        self.assertIsNone(html)

    def test_get_changes_groups_by_day_and_ignores_stray_files(self):
        self._write("changes/2026-08-13.md", "### Added\nsomething\n")
        self._write("changes/2026-08-12.md", "### Changed\nsomething else\n")
        self._write("changes/notes.md", "ignored\n")
        with self._patch_path():
            changes = self.book._read_module_changes("connect")
        dates = [date for date, _html in changes]
        self.assertEqual(sorted(dates), ["2026-08-12", "2026-08-13"])

    def test_get_book_returns_page_shape(self):
        self._write("user_guide.md", "# Guide\n")
        with self._patch_path():
            pages = self.book.get_book()["pages"]
        self.assertTrue(pages)
        self.assertEqual(
            sorted(pages[0]), ["html", "id", "module", "title"]
        )
