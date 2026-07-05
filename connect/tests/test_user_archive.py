# -*- coding: utf-8 -*-
from unittest.mock import patch, MagicMock
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestUserArchive(TransactionCase):
    """Archiving a Connect User must remove its telephony access (SIP account +
    Connect groups); unarchiving must recreate the SIP account with a fresh
    password. See ODU-272."""

    def setUp(self):
        super().setUp()
        self.env["connect.settings"].set_param("twilio_auto_sync", True)
        self.domain = self.env["connect.domain"].with_context(
            no_twilio_create=True).create({
                "subdomain": "testarchive",
                "friendly_name": "Test Archive",
                "cred_list_sid": "CLtest",
            })
        self.res_user = self.env["res.users"].create({
            "name": "Arch Test",
            "login": "archtest@example.com",
        })

    def _make_client(self, create_sid="CRnew"):
        client = MagicMock()
        client.sip.credential_lists.return_value.credentials.create.return_value.sid = create_sid
        return client

    def _patch_client(self, client):
        return patch.object(
            type(self.env["connect.settings"]), "get_client", return_value=client)

    def _create_user(self, client):
        with self._patch_client(client):
            return self.env["connect.user"].create({
                "username": "archuser",
                "domain": self.domain.id,
                "user": self.res_user.id,
                "sip_enabled": True,
                "password": "StrongPassw0rd1",
            })

    def test_create_provisions_sip_and_group(self):
        user = self._create_user(self._make_client("CRnew"))
        self.assertEqual(user.sid, "CRnew")
        self.assertTrue(self.res_user.has_group("connect.group_connect_user"))

    def test_archive_deletes_sip_and_removes_group(self):
        client = self._make_client()
        user = self._create_user(client)
        with self._patch_client(client):
            user.action_archive()
        self.assertFalse(user.active)
        # SID cleared so the account is recreated cleanly on restore.
        self.assertFalse(user.sid)
        client.sip.credential_lists.return_value.credentials.return_value.delete.assert_called_once()
        # Telephony access revoked at the Odoo level too.
        self.assertFalse(self.res_user.has_group("connect.group_connect_user"))

    def test_unarchive_recreates_sip_with_new_password(self):
        user = self._create_user(self._make_client())
        with self._patch_client(self._make_client()):
            user.action_archive()
        self.assertFalse(user.sid)

        restore_client = self._make_client(create_sid="CRrestored")
        with self._patch_client(restore_client):
            user.action_unarchive()

        self.assertTrue(user.active)
        self.assertEqual(user.sid, "CRrestored")
        restore_client.sip.credential_lists.return_value.credentials.create.assert_called_once()
        self.assertTrue(self.res_user.has_group("connect.group_connect_user"))

    def test_archived_user_is_not_routable(self):
        user = self._create_user(self._make_client())
        with self._patch_client(self._make_client()):
            user.action_archive()
        # Default active_test excludes archived users from call routing lookups.
        found = self.env["connect.user"].get_user_by_uri("sip:archuser@example.com")
        self.assertFalse(found)
        self.assertFalse(
            self.env["connect.user"].search([("username", "=", "archuser")]))
