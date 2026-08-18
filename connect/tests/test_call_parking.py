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

    def test_a_call_can_be_parked_and_retrieved_repeatedly(self):
        """The same customer is parked, taken back and parked again.

        Covers both halves of the cycle: the slot bookkeeping has to survive
        the retrieval Dial action clearing it when the previous retrieval
        finished, and every retrieval must still dial back presenting the
        customer's own number rather than the parking slot.
        """
        parked = self._make_call('CAcustomer', '+12898283865', '+13658257665',
                                 'incoming', self.partner)
        for round_no, slot in enumerate(('701', '702', '701'), start=1):
            where = 'round %s (slot %s)' % (round_no, slot)
            self._park('CAcustomer', slot=slot)
            parked.invalidate_recordset()
            self.assertEqual(parked.park_slot, slot, where)
            self.assertEqual(parked.park_call_sid, 'CAcustomer', where)

            twilio = MagicMock()
            with patch.object(type(self.env['connect.settings']), 'get_client',
                              return_value=twilio):
                response = self.env['connect.call'].unpark_call(
                    {'CallSid': 'CAslotleg%s' % round_no, 'Caller': self.agent_uri},
                    {'ExtenNumber': slot})
            # The parked call dials the agent back, so the leg that dialled the
            # slot is released rather than bridged through the queue.
            self.assertIn('<Hangup', str(response), where)
            twiml = twilio.calls.return_value.update.call_args.kwargs['twiml']
            self.assertIn('callerId="+12898283865"', twiml, where)
            self.assertNotIn('<Queue', twiml, where)

            # Twilio reports the retrieval Dial as finished, as it does live.
            self.env['connect.call'].on_park_retrieve_action(
                parked.id, slot, {'DialCallStatus': 'completed'})
            parked.invalidate_recordset()

    def test_a_stale_action_does_not_clear_a_re_park_into_the_same_slot(self):
        """Taking a call back and parking it in the slot it came from is the
        most common way to re-park, so the slot number alone cannot tell a
        stale action apart from a live one."""
        parked = self._make_call('CAcustomer', '+12898283865', '+13658257665',
                                 'incoming', self.partner)
        self._park('CAcustomer')
        parked.park_slot = False  # retrieved
        self._park('CAcustomer')  # ...and parked again, same slot
        response = self.env['connect.call'].on_park_retrieve_action(
            parked.id, '702', {'DialCallStatus': 'completed'})
        self.assertIn('<Enqueue>park-702</Enqueue>', str(response))
        self.assertEqual(parked.park_slot, '702')
        self.assertEqual(parked.park_call_sid, 'CAcustomer')

    def test_answered_retrieval_clears_the_parking_state(self):
        parked = self._make_call('CAcustomer', '+12898283865', '+13658257665',
                                 'incoming', self.partner)
        self._park('CAcustomer')
        # Retrieval takes the call out of its slot before the Dial even runs,
        # so a completed action always sees a call that is no longer parked.
        parked.park_slot = False
        response = self.env['connect.call'].on_park_retrieve_action(
            parked.id, '702', {'DialCallStatus': 'completed'})
        self.assertIn('<Hangup', str(response))
        self.assertFalse(parked.park_slot)
        self.assertFalse(parked.park_call_sid)

    def test_an_ended_call_does_not_hold_its_slot(self):
        """A caller who hung up while on hold must release the slot.

        Retrieving a dead call cannot work — Twilio refuses to redirect it —
        and the fallback queue bridge that follows carries no referUrl, so the
        agent who picks the call up can never park it again.
        """
        stale = self._make_call('CAstale', '+12898283865', '+13658257665',
                                'incoming')
        self._park('CAstale')
        stale.status = 'completed'
        self.assertFalse(self.env['connect.call']._get_parked_call('702'))

    def test_a_stale_slot_registration_does_not_hijack_a_retrieval(self):
        """The live caller is retrieved even when a dead one holds the slot."""
        stale = self._make_call('CAstale', '+12898283865', '+13658257665',
                                'incoming')
        self._park('CAstale')
        stale.status = 'completed'
        live = self._make_call('CAlive', '+12898283866', '+13658257665',
                               'incoming', self.partner)
        self._park('CAlive')

        twilio = MagicMock()
        with patch.object(type(self.env['connect.settings']), 'get_client',
                          return_value=twilio):
            response = self.env['connect.call'].unpark_call(
                {'CallSid': 'CAslotleg', 'Caller': self.agent_uri},
                {'ExtenNumber': '702'})

        self.assertIn('<Hangup', str(response))
        self.assertEqual(twilio.calls.call_args.args[0], 'CAlive')
        self.assertEqual(live.park_slot, False)
        twiml = twilio.calls.return_value.update.call_args.kwargs['twiml']
        self.assertIn('callerId="+12898283866"', twiml)
        # The retrieval Dial keeps a referUrl, which is what lets the agent
        # park the very same conversation a second time.
        self.assertIn('referUrl=', twiml)
