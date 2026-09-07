# -*- coding: utf-8 -*-
from unittest.mock import MagicMock, patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


def twilio_call(sid, parent_call_sid=None, status='in-progress'):
    """A Twilio call resource with real attribute values.

    A bare MagicMock cannot be used here: `debug_current_call_state` reads
    `parent_call_sid` and a MagicMock attribute is always truthy, which would
    silently send every transfer to a non-existent parent leg.
    """
    call = MagicMock()
    call.sid = sid
    call.status = status
    call.direction = 'inbound'
    call.parent_call_sid = parent_call_sid
    call.start_time = None
    call.end_time = None
    call.duration = 0
    return call


@tagged("post_install", "-at_install")
class TestParkTransfer(TransactionCase):
    """Transferring again a call that was just retrieved from a parking slot.

    Retrieval inverts the leg topology: the customer becomes the parent leg
    running a <Dial> towards the agent, and that <Dial> carries the
    park_retrieve action URL. A second transfer has to survive that.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['connect.settings'].set_param('api_url', 'https://pbx.example.com/')
        cls.partner = cls.env['res.partner'].create({
            'name': 'Acme Customer', 'phone': '+12898283865',
        })
        # connect.user.user is unique, so the target needs an Odoo user of its
        # own rather than a shared one such as the admin.
        cls.target_odoo_user = cls.env['res.users'].create({
            'name': 'Park Target', 'login': 'park.target@example.com',
        })
        with patch.object(type(cls.env['connect.settings']), 'get_client',
                          return_value=MagicMock()):
            cls.domain = cls.env['connect.domain'].with_context(
                no_twilio_create=True).create({
                    'subdomain': 'test-park-transfer',
                    'friendly_name': 'Test Park Transfer',
                })
            # The agent who retrieves the parked call, on a SIP desk phone.
            cls.retriever = cls.env['connect.user'].with_context(
                no_twilio_create=True).create({
                    'username': 'ParkRetriever', 'domain': cls.domain.id,
                    'sip_enabled': True, 'client_enabled': False,
                    'record_calls': False,
                })
            # The agent the call is transferred on to.
            cls.target = cls.env['connect.user'].with_context(
                no_twilio_create=True).create({
                    'username': 'ParkTarget', 'domain': cls.domain.id,
                    'sip_enabled': True, 'client_enabled': False,
                    'record_calls': False,
                    'user': cls.target_odoo_user.id,
                })
        cls.retriever_exten = cls._make_exten('7801', cls.retriever)
        cls.target_exten = cls._make_exten('7802', cls.target)
        cls.retriever_uri = 'sip:ParkRetriever@%s' % cls.domain.domain_name
        cls.target_uri = 'sip:ParkTarget@%s' % cls.domain.domain_name

    @classmethod
    def _make_exten(cls, number, pbx_user):
        exten = cls.env['connect.exten'].create({
            'number': number, 'model': 'connect.user', 'res_id': pbx_user.id,
        })
        pbx_user.exten = exten.id
        return exten

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

    def _park_and_retrieve(self, slot='702'):
        """Drive a call through park -> retrieve and return the parked call.

        Leaves the database in the state a retrieved call is really in: the
        customer leg is out of the queue and dialing the retriever, park_slot
        is cleared but park_call_sid is kept so an unanswered retrieval can
        re-park.
        """
        parked = self._make_call('CAcustomer', '+12898283865', '+13658257665',
                                 'incoming', self.partner)
        self.env['connect.call'].park_call(
            {'CallSid': 'CAcustomer', 'Caller': self.retriever_uri},
            {'ExtenNumber': '*%s' % slot})
        # The leg the retriever dialed the slot with.
        self._make_call('CAretrieval', '7801', slot, 'outgoing')
        with patch.object(type(self.env['connect.settings']), 'get_client',
                          return_value=MagicMock()):
            self.env['connect.call'].unpark_call(
                {'CallSid': 'CAretrieval', 'Caller': self.retriever_uri},
                {'ExtenNumber': slot})
        parked.invalidate_recordset()
        return parked

    def _attach_agent_leg(self, call, sid='CAagentleg'):
        """The leg Twilio creates when the customer dials the agent back."""
        return self.env['connect.channel'].create({
            'sid': sid, 'call': call.id, 'caller': '+12898283865',
            'called': self.retriever_uri, 'status': 'in-progress',
            'technical_direction': 'outbound-dial',
        })

    # ------------------------------------------------------------------
    # The retrieval <Dial action=...> must not override a second transfer
    # ------------------------------------------------------------------

    def test_transfer_after_retrieval_leaves_no_parking_state_behind(self):
        """A blind transfer ends the agent leg, so Twilio fetches the
        park_retrieve action of the retrieval Dial.

        Measured against live Twilio on 2026-08-05: the action is requested,
        but its TwiML is discarded because the SIP REFER has already replaced
        the call's document — the caller went on to reach the transfer target
        and only ended 15 seconds later. What matters here is therefore the
        database write rather than the response: the call is no longer parked,
        and nothing may be left pointing at a slot it is not waiting in.
        """
        parked = self._park_and_retrieve()
        parked.add_transferred_user(self.target.user)
        self.env['connect.call'].on_park_retrieve_action(
            parked.id, '702', {'DialCallStatus': 'completed'})
        parked.invalidate_recordset()
        self.assertFalse(parked.park_slot)
        self.assertFalse(parked.park_call_sid)

    def test_unanswered_retrieval_still_reparks_when_no_transfer_is_pending(self):
        """The re-park behaviour itself must stay intact for a plain
        unanswered retrieval."""
        parked = self._park_and_retrieve()
        response = self.env['connect.call'].on_park_retrieve_action(
            parked.id, '702', {'DialCallStatus': 'no-answer'})
        self.assertIn('<Enqueue>park-702</Enqueue>', str(response))
        self.assertEqual(parked.park_slot, '702')

    def test_repark_after_retrieval_survives_the_stale_dial_action(self):
        """Parking a retrieved call again races the retrieval Dial action.

        The action fires when the old Dial ends and clears park_slot /
        park_call_sid, wiping the tracking the new park just wrote.
        """
        parked = self._park_and_retrieve()
        # The agent parks the call again, in another slot.
        self.env['connect.call'].park_call(
            {'CallSid': 'CAcustomer', 'Caller': self.retriever_uri},
            {'ExtenNumber': '*703'})
        parked.invalidate_recordset()
        self.assertEqual(parked.park_slot, '703')
        # Twilio now reports the previous retrieval Dial as finished.
        self.env['connect.call'].on_park_retrieve_action(
            parked.id, '702', {'DialCallStatus': 'completed'})
        parked.invalidate_recordset()
        self.assertEqual(parked.park_slot, '703',
                         'A stale retrieval action cleared the new parking slot.')
        self.assertEqual(parked.park_call_sid, 'CAcustomer',
                         'A stale retrieval action cleared the parked call SID.')

    # ------------------------------------------------------------------
    # SIP REFER path
    # ------------------------------------------------------------------

    def test_sip_refer_after_retrieval_dials_the_new_target(self):
        """The desk phone transfer must reach the new extension, not loop
        back to the agent who is transferring."""
        parked = self._park_and_retrieve()
        self._attach_agent_leg(parked)
        response = self.env['connect.user'].handle_sip_refer({
            'CallSid': 'CAagentleg',
            'Caller': self.retriever_uri,
            'ReferTransferTarget': '<sip:7802@%s>' % self.domain.domain_name,
        })
        self.assertIn(self.target_uri, str(response))
        self.assertNotIn(self.retriever_uri, str(response),
                         'The transfer dialed the retriever back.')

    # ------------------------------------------------------------------
    # Web widget path (connect.transfer_wizard)
    # ------------------------------------------------------------------

    def _execute_widget_transfer(self, session_id, parent_call_sid):
        """Run the wizard the way phone.js does: call_id is always None."""
        client = MagicMock()
        client.calls.return_value.fetch.return_value = twilio_call(
            session_id, parent_call_sid=parent_call_sid)
        with patch.object(type(self.env['connect.settings']), 'get_client',
                          return_value=client):
            result = self.env['connect.transfer_wizard'].execute_transfer(
                '7802', 'blind', None, session_id)
        return result, client

    def test_widget_transfer_after_retrieval_redirects_the_customer(self):
        """The customer leg, not the agent leg, must be redirected to the
        new extension."""
        parked = self._park_and_retrieve()
        self._attach_agent_leg(parked)
        result, client = self._execute_widget_transfer('CAagentleg', 'CAcustomer')
        self.assertTrue(result['success'], result.get('error'))
        updated_sids = [c.args[0] for c in client.calls.call_args_list
                        if c.args and isinstance(c.args[0], str)]
        self.assertIn('CAcustomer', updated_sids)
        twiml = client.calls.return_value.update.call_args.kwargs['twiml']
        self.assertIn('/connect/7802', twiml)
        self.assertNotIn('/connect/7801', twiml,
                         'The transfer redirected back to the retriever.')

    def test_widget_transfer_works_when_bound_to_the_retrieval_call(self):
        """The agent leg may resolve to the "agent -> slot" retrieval record,
        which is an outgoing call with no external leg to redirect."""
        self._park_and_retrieve()
        retrieval = self.env['connect.channel'].search(
            [('sid', '=', 'CAretrieval')], limit=1).call
        self.assertEqual(retrieval.direction, 'outgoing')
        self._attach_agent_leg(retrieval, sid='CAagentleg2')
        result, client = self._execute_widget_transfer('CAagentleg2', 'CAcustomer')
        self.assertTrue(result['success'], result.get('error'))
        twiml = client.calls.return_value.update.call_args.kwargs['twiml']
        self.assertIn('/connect/7802', twiml)

    def test_transfer_to_an_extension_without_an_odoo_user_does_not_fail(self):
        """connect.user.user is optional; the wizard must not blow up when the
        transfer target has no linked Odoo user."""
        with patch.object(type(self.env['connect.settings']), 'get_client',
                          return_value=MagicMock()):
            orphan = self.env['connect.user'].with_context(
                no_twilio_create=True).create({
                    'username': 'ParkOrphan', 'domain': self.domain.id,
                    'sip_enabled': True, 'client_enabled': False,
                    'record_calls': False,
                })
        self._make_exten('7803', orphan)
        parked = self._park_and_retrieve()
        self._attach_agent_leg(parked)
        client = MagicMock()
        client.calls.return_value.fetch.return_value = twilio_call(
            'CAagentleg', parent_call_sid='CAcustomer')
        with patch.object(type(self.env['connect.settings']), 'get_client',
                          return_value=client):
            result = self.env['connect.transfer_wizard'].execute_transfer(
                '7803', 'blind', None, 'CAagentleg')
        self.assertTrue(result['success'], result.get('error'))

    # ------------------------------------------------------------------
    # Outgoing transfer without a tracked external leg
    # ------------------------------------------------------------------

    def test_outgoing_transfer_without_external_leg_is_refused(self):
        """An ordinary outgoing call must not have its agent leg redirected.

        When the external leg is untracked (a late or lost child webhook),
        the SID the wizard holds is the agent leg running the <Dial>.
        Replacing its TwiML would tear that Dial down and drop the customer,
        so the transfer has to fail and leave the call up instead.
        """
        self._make_call('CAoutgoing', '7801', '+12898283865', 'outgoing')
        result, client = self._execute_widget_transfer('CAoutgoing', None)
        self.assertFalse(result['success'])
        client.calls.return_value.update.assert_not_called()

    def test_park_retrieval_without_external_leg_still_redirects(self):
        """The retrieval leg keeps the direct-redirect fallback.

        Its "agent -> slot" record is outgoing and never has an external leg;
        _link_park_retrieval_leg attaches it to the parked call, which is what
        tells the wizard the fallback is safe here.
        """
        self._park_and_retrieve()
        retrieval = self.env['connect.channel'].search(
            [('sid', '=', 'CAretrieval')]).call
        self.assertTrue(retrieval._is_park_retrieval())
        result, client = self._execute_widget_transfer('CAretrieval', None)
        self.assertTrue(result['success'], result.get('error'))
        updated_sids = [c.args[0] for c in client.calls.call_args_list
                        if c.args and isinstance(c.args[0], str)]
        self.assertIn('CAretrieval', updated_sids)
