# -*- coding: utf-8 -*-
from unittest.mock import MagicMock, patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestCallParking(TransactionCase):
    """Park / retrieve keeps the customer's caller ID and call history."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['connect.settings'].set_param('api_url', 'https://pbx.example.com/')
        cls.partner = cls.env['res.partner'].create({
            'name': 'Acme Customer', 'phone': '+12898283865',
        })
        # Twilio is never reachable from tests: the domain create() builds a
        # client even when no_twilio_create skips the provisioning itself.
        with patch.object(type(cls.env['connect.settings']), 'get_client',
                          return_value=MagicMock()):
            cls.domain = cls.env['connect.domain'].with_context(
                no_twilio_create=True).create({
                    'subdomain': 'test-parking', 'friendly_name': 'Test Parking',
                })
            cls.agent = cls.env['connect.user'].with_context(
                no_twilio_create=True).create({
                    'username': 'ParkTester', 'domain': cls.domain.id,
                    'sip_enabled': True, 'client_enabled': False,
                    'record_calls': False,
                })
        cls.agent_uri = 'sip:ParkTester@%s' % cls.domain.domain_name

    def _make_call(self, sid, caller, called, direction, partner=None):
        call = self.env['connect.call'].create({
            'caller': caller, 'called': called, 'direction': direction,
            'status': 'in-progress', 'partner': partner.id if partner else False,
        })
        self.env['connect.channel'].create({
            'sid': sid, 'call': call.id, 'caller': caller, 'called': called,
            'status': 'in-progress', 'technical_direction': 'inbound',
        })
        return call

    def _park(self, call_sid, slot='702'):
        return self.env['connect.call'].park_call(
            {'CallSid': call_sid, 'Caller': self.agent_uri},
            {'ExtenNumber': '*%s' % slot})

    def test_park_records_slot_on_the_call(self):
        call = self._make_call('CAcustomer', '+12898283865', '+13658257665',
                               'incoming', self.partner)
        self._park('CAcustomer')
        self.assertEqual(call.park_slot, '702')
        self.assertEqual(call.park_call_sid, 'CAcustomer')
        self.assertEqual(call.parked_by_pbx_user, self.agent)
        self.assertTrue(call.parked_at)

    def test_retrieval_dials_back_with_the_original_caller_id(self):
        parked = self._make_call('CAcustomer', '+12898283865', '+13658257665',
                                 'incoming', self.partner)
        self._park('CAcustomer')
        retrieval = self._make_call('CAretrieval', '206', '702', 'outgoing')
        twilio = MagicMock()
        with patch.object(type(self.env['connect.settings']), 'get_client',
                          return_value=twilio):
            response = self.env['connect.call'].unpark_call(
                {'CallSid': 'CAretrieval', 'Caller': self.agent_uri},
                {'ExtenNumber': '702'})
        # The agent's "dialed the slot" leg is released...
        self.assertIn('<Hangup', str(response))
        self.assertNotIn('<Queue', str(response))
        # ...and the parked call dials the agent back with the customer's number.
        twilio.calls.assert_called_once_with('CAcustomer')
        twiml = twilio.calls.return_value.update.call_args.kwargs['twiml']
        self.assertIn('callerId="+12898283865"', twiml)
        self.assertIn(self.agent_uri, twiml)
        self.assertNotIn('<Queue', twiml)
        # Slot is freed, the SID is kept so an unanswered retrieval can re-park.
        self.assertFalse(parked.park_slot)
        self.assertEqual(parked.park_call_sid, 'CAcustomer')
        # The retrieval leg is no longer an orphan "206 -> 702" call.
        self.assertEqual(retrieval.parent_call, parked)
        self.assertEqual(retrieval.partner, self.partner)

    def test_retrieval_falls_back_to_queue_when_nothing_is_tracked(self):
        self._make_call('CAretrieval', '206', '702', 'outgoing')
        response = self.env['connect.call'].unpark_call(
            {'CallSid': 'CAretrieval', 'Caller': self.agent_uri},
            {'ExtenNumber': '702'})
        self.assertIn('<Queue>park-702</Queue>', str(response))

    def test_retrieval_falls_back_to_queue_on_twilio_error(self):
        parked = self._make_call('CAcustomer', '+12898283865', '+13658257665',
                                 'incoming', self.partner)
        self._park('CAcustomer')
        twilio = MagicMock()
        twilio.calls.return_value.update.side_effect = Exception('Twilio is down')
        with patch.object(type(self.env['connect.settings']), 'get_client',
                          return_value=twilio):
            response = self.env['connect.call'].unpark_call(
                {'CallSid': 'CAretrieval', 'Caller': self.agent_uri},
                {'ExtenNumber': '702'})
        self.assertIn('<Queue>park-702</Queue>', str(response))
        # The call stays parked, so a later retrieval can still find it.
        self.assertEqual(parked.park_slot, '702')

    def test_unanswered_retrieval_re_parks_the_caller(self):
        parked = self._make_call('CAcustomer', '+12898283865', '+13658257665',
                                 'incoming', self.partner)
        self._park('CAcustomer')
        parked.park_slot = False
        response = self.env['connect.call'].on_park_retrieve_action(
            parked.id, '702', {'DialCallStatus': 'no-answer'})
        self.assertIn('<Enqueue>park-702</Enqueue>', str(response))
        self.assertEqual(parked.park_slot, '702')

    def test_answered_retrieval_clears_the_parking_state(self):
        parked = self._make_call('CAcustomer', '+12898283865', '+13658257665',
                                 'incoming', self.partner)
        self._park('CAcustomer')
        response = self.env['connect.call'].on_park_retrieve_action(
            parked.id, '702', {'DialCallStatus': 'completed'})
        self.assertIn('<Hangup', str(response))
        self.assertFalse(parked.park_slot)
        self.assertFalse(parked.park_call_sid)
