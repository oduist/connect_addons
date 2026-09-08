# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


class _Sent:
    """Stands in for the Twilio message client_send returns."""
    sid = 'SMcomposer'
    account_sid = 'ACtest'
    messaging_service_sid = False
    num_media = 0
    error_code = None
    error_message = None


@tagged('post_install', '-at_install')
class TestSmsComposer(TransactionCase):
    """Sending from the composer in every shape core opens it in.

    555-01xx is the reserved fictional range: a real number would match live
    data in this database and the assertions would describe that instead of
    their own fixture.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Message = cls.env['connect.message']
        cls.first = cls.env['res.partner'].create({
            'name': 'Batch One', 'phone': '+12125550142'})
        cls.second = cls.env['res.partner'].create({
            'name': 'Batch Two', 'phone': '+12125550143'})
        cls.no_phone = cls.env['res.partner'].create({'name': 'Numberless Ned'})
        cls.line = cls.env['connect.outgoing_callerid'].create({
            'friendly_name': 'Main line', 'number': '+15559990000',
            'callerid_type': 'number', 'is_default': True,
        })
        # This database carries the deployment's real Twilio numbers; take them
        # out of the messaging lines so the sender is the fixture's own.
        cls.env['connect.outgoing_callerid'].search([
            ('id', '!=', cls.line.id), ('callerid_type', '=', 'number'),
        ]).write({'callerid_type': 'outgoing_callerid', 'status': 'validated'})

    def _batch_composer(self, records):
        """The composer as a server action or a list-view send opens it."""
        return self.env['sms.composer'].with_context(
            default_res_model=records._name,
            default_res_ids=repr(records.ids),
            default_composition_mode='mass',
        ).create({'body': 'Hi {{ object.name }}'})

    def test_batch_send_uses_each_records_own_number(self):
        """Batch mode never fills recipient_single_number. Reading it anyway
        sent every message to an empty recipient, which Twilio rejected as a
        short code."""
        composer = self._batch_composer(self.first | self.second)
        self.assertEqual(composer.composition_mode, 'mass')
        self.assertFalse(composer.recipient_single_number)

        with patch.object(type(self.Message), 'client_send', return_value=_Sent()) as sent:
            composer.action_send_sms()

        self.assertEqual([call.args[0] for call in sent.call_args_list],
                         ['+12125550142', '+12125550143'])
        self.assertEqual([call.args[2] for call in sent.call_args_list],
                         ['Hi Batch One', 'Hi Batch Two'],
                         'each record renders its own body')

    def test_comment_mode_batch_send_resolves_numbers_too(self):
        """A server action set to 'SMS (with note)' composes in comment mode,
        but it passes res_ids and never res_id -- so comment_single_recipient
        stays off and it is a batch like any other. Switching an action to
        comment mode was tried as a way round the empty recipient; it is not
        one, and this is why."""
        composer = self.env['sms.composer'].with_context(
            default_res_model='res.partner',
            default_res_ids=repr((self.first | self.second).ids),
            default_composition_mode='comment',
        ).create({'body': 'Hi {{ object.name }}'})
        self.assertFalse(composer.res_id)
        self.assertFalse(composer.comment_single_recipient)
        self.assertFalse(composer.recipient_single_number)

        with patch.object(type(self.Message), 'client_send', return_value=_Sent()) as sent:
            composer.action_send_sms()

        self.assertEqual([call.args[0] for call in sent.call_args_list],
                         ['+12125550142', '+12125550143'])

    def test_batch_send_names_the_record_it_cannot_reach(self):
        """Which contact is missing a number, rather than 'unexpected error'."""
        composer = self._batch_composer(self.first | self.no_phone)
        with patch.object(type(self.Message), 'client_send', return_value=_Sent()) as sent:
            with self.assertRaises(ValidationError) as caught:
                composer.action_send_sms()
        self.assertIn('Numberless Ned', str(caught.exception))
        self.assertFalse(sent.called,
                         'no message may go out while part of the batch cannot')

    def test_single_recipient_send_still_works(self):
        composer = self.env['sms.composer'].with_context(
            default_res_model='res.partner',
            default_res_id=self.first.id,
            default_composition_mode='comment',
        ).create({'body': 'one off'})
        self.assertTrue(composer.comment_single_recipient)

        with patch.object(type(self.Message), 'client_send', return_value=_Sent()) as sent:
            composer.action_send_sms()

        self.assertEqual(sent.call_args.args[0], '+12125550142')
        self.assertEqual(sent.call_args.args[2], 'one off')

    def test_single_recipient_send_honours_the_edited_number(self):
        """The number typed into the composer is the one that gets the message."""
        composer = self.env['sms.composer'].with_context(
            default_res_model='res.partner',
            default_res_id=self.first.id,
            default_composition_mode='comment',
        ).create({'body': 'corrected'})
        composer.recipient_single_number_itf = '+12125550188'

        with patch.object(type(self.Message), 'client_send', return_value=_Sent()) as sent:
            composer.action_send_sms()

        self.assertEqual(sent.call_args.args[0], '+12125550188')

    def test_failed_send_reports_what_the_provider_refused(self):
        """'Unexpected error! Contact admin or maintainer!' told the user
        nothing and left the reason in the container log."""
        class _Refused(Exception):
            msg = "Unable to create record: 'To' number cannot be a Short Code: FXXXX"

        Settings = type(self.env['connect.settings'])
        with patch.object(Settings, 'get_client') as get_client:
            get_client.return_value.messages.create.side_effect = _Refused()
            with self.assertRaises(ValidationError) as caught:
                self.Message.send('+12125550142', 'hello')

        self.assertIn('Short Code', str(caught.exception))
