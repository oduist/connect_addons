# -*- coding: utf-8 -*-
from unittest.mock import MagicMock, patch

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from twilio.base.exceptions import TwilioRestException

URI = '/Accounts/ACtest/Applications/APgone.json'

OTHER_SYNCS = [
    'connect.domain', 'connect.number', 'connect.outgoing_callerid',
    'connect.whatsapp_sender', 'connect.message_content_template',
]


def rest_error(status, msg, code=None):
    return TwilioRestException(status, URI, msg, code=code, method='POST')


@tagged("post_install", "-at_install")
class TestTwiMLSync(TransactionCase):
    """Syncing TwiML apps tells a missing app apart from a broken request."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        settings = cls.env['connect.settings']
        settings.set_param('api_url', 'https://pbx.example.com/')
        settings.set_param('account_sid', 'AC' + '0' * 30)
        settings.set_param('auth_token', 'a' * 32)
        # write() would push each change straight to Twilio, these tests call
        # sync() explicitly instead.
        settings.set_param('twilio_auto_sync', False)

    def _app(self, name, sid, old_sid=False):
        return self.env['connect.twiml'].with_context(install_mode=True).create({
            'name': name, 'sid': sid, 'old_sid': old_sid,
        })

    def _client(self, failing, error, new_sid='APnew'):
        """A Twilio client that only fails for the given app SIDs.

        The database ships with TwiML apps of its own and sync() walks all of
        them, so every other SID has to answer normally.
        """
        client = MagicMock()
        broken = MagicMock()
        broken.update.side_effect = error
        broken.fetch.side_effect = error
        client.applications.side_effect = lambda sid: (
            broken if sid in failing else MagicMock())
        client.applications.create.return_value.sid = new_sid
        return client

    def _sync(self, client):
        with patch.object(type(self.env['connect.settings']), 'get_client',
                          return_value=client):
            return self.env['connect.twiml'].sync()

    def _settings_sync(self, client):
        settings = self.env['connect.settings'].search([], limit=1)
        for model in OTHER_SYNCS:
            patcher = patch.object(type(self.env[model]), 'sync',
                                   return_value=None)
            patcher.start()
            self.addCleanup(patcher.stop)
        with patch.object(type(settings), 'get_client', return_value=client):
            return settings.sync()

    def test_a_404_recreates_the_app_whatever_the_message_says(self):
        # Twilio does not promise the words "not found" in the body: the 401
        # seen in production carried "Authenticate" and nothing else.
        app = self._app('Reject', 'APgone')
        client = self._client(
            {'APgone'}, rest_error(404, 'Unable to update record', code=20404))
        self.assertEqual(self._sync(client), [])
        client.applications.create.assert_called_once()
        self.assertEqual(app.sid, 'APnew')
        self.assertEqual(app.old_sid, 'APgone')

    def test_a_404_on_the_old_sid_lookup_falls_back_to_creating_an_app(self):
        app = self._app('Reject', 'APgone', old_sid='APolder')
        client = self._client(
            {'APgone', 'APolder'},
            rest_error(404, 'Unable to update record', code=20404))
        self.assertEqual(self._sync(client), [])
        client.applications.create.assert_called_once()
        self.assertEqual(app.sid, 'APnew')

    def test_one_failing_app_does_not_abort_the_rest_of_the_sync(self):
        broken = self._app('A Broken', 'APbroken')
        healthy = self._app('B Healthy', 'APhealthy')
        client = self._client(
            {'APbroken'},
            rest_error(500, 'An internal server error has occurred', code=20500))
        errors = self._sync(client)
        self.assertEqual(
            errors, ['A Broken: An internal server error has occurred'])
        # A server-side blip is not mistaken for a missing app.
        client.applications.create.assert_not_called()
        self.assertEqual(broken.sid, 'APbroken')
        self.assertEqual(healthy.sid, 'APhealthy')

    def test_a_failed_app_is_reported_back_to_the_user(self):
        self._app('A Broken', 'APbroken')
        client = self._client(
            {'APbroken'},
            rest_error(500, 'An internal server error has occurred', code=20500))
        action = self._settings_sync(client)
        self.assertEqual(action['tag'], 'display_notification')
        self.assertEqual(action['params']['type'], 'warning')
        self.assertIn('A Broken', action['params']['message'])

    def test_a_successful_sync_reports_nothing(self):
        self._app('A Fine', 'APfine')
        self.assertIsNone(self._settings_sync(self._client(set(), None)))

    def test_a_rejected_token_aborts_the_sync_with_a_readable_message(self):
        self._app('Reject', 'APgone')
        client = self._client(
            {'APgone'}, rest_error(401, 'Unable to update record: Authenticate'))
        with self.assertRaises(ValidationError) as error:
            self._settings_sync(client)
        self.assertIn('Auth Token', str(error.exception))
        client.applications.create.assert_not_called()
