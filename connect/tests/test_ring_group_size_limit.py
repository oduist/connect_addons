# -*- coding: utf-8 -*-
from unittest.mock import MagicMock, patch

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestRingGroupSizeLimit(TransactionCase):
    """A ring group cannot hold more users than Twilio will ever dial.

    Twilio dials at most ten parallel targets per <Dial>. A live
    thirteen-target ring group rang nobody past the tenth route and
    registered a leg expectation no webhook sequence could satisfy, so
    the form now refuses to save more than ten ring users.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['connect.settings'].set_param('api_url', 'https://pbx.example.com/')
        with patch.object(type(cls.env['connect.settings']), 'get_client',
                          return_value=MagicMock()):
            cls.domain = cls.env['connect.domain'].with_context(
                no_twilio_create=True).create({
                    'subdomain': 'test-ring-limit', 'friendly_name': 'Test Ring Limit',
                })
            cls.agents = cls.env['connect.user']
            for n in range(11):
                cls.agents |= cls.env['connect.user'].with_context(
                    no_twilio_create=True).create({
                        'username': 'LimitAgent%02d' % n, 'domain': cls.domain.id,
                        'sip_enabled': True, 'client_enabled': False,
                        'record_calls': False,
                    })

    def test_ten_ring_users_are_accepted(self):
        flow = self.env['connect.callflow'].create({
            'name': 'Ring Ten', 'voice': 'man', 'prompt_message': False,
            'ring_users': [(6, 0, self.agents[:10].ids)],
        })
        self.assertEqual(len(flow.ring_users), 10)

    def test_eleventh_ring_user_is_refused(self):
        with self.assertRaises(ValidationError):
            self.env['connect.callflow'].create({
                'name': 'Ring Eleven', 'voice': 'man', 'prompt_message': False,
                'ring_users': [(6, 0, self.agents.ids)],
            })

        flow = self.env['connect.callflow'].create({
            'name': 'Ring Ten Then Eleven', 'voice': 'man', 'prompt_message': False,
            'ring_users': [(6, 0, self.agents[:10].ids)],
        })
        with self.assertRaises(ValidationError):
            flow.ring_users = [(4, self.agents[10].id)]
