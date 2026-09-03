# -*- coding: utf-8 -*-
from unittest.mock import MagicMock, patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestDirectCallFinalization(TransactionCase):
    """An incoming direct call must finalize once every leg has ended.

    Regression test for a live call that stayed at "ringing" forever: the
    dial to the answering client user registers a direct_call runtime
    attempt, but the client leg is created before the call pattern is known,
    so it carries no call_source and the legacy expectation helper (which
    matches attempts by call_source only) never resolved the attempt. The
    pending attempt then blocked finalization for good.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['connect.settings'].set_param('api_url', 'https://pbx.example.com/')
        cls.agent_user = cls.env['res.users'].create({
            'name': 'Direct Agent', 'login': 'direct.agent@example.com',
            'email': 'direct.agent@example.com',
        })
        with patch.object(type(cls.env['connect.settings']), 'get_client',
                          return_value=MagicMock()):
            cls.domain = cls.env['connect.domain'].with_context(
                no_twilio_create=True).create({
                    'subdomain': 'test-direct', 'friendly_name': 'Test Direct',
                })
            cls.agent = cls.env['connect.user'].with_context(
                no_twilio_create=True).create({
                    'username': 'DirectAgent', 'domain': cls.domain.id,
                    'user': cls.agent_user.id,
                    'sip_enabled': False, 'client_enabled': True,
                    'record_calls': False,
                })

    def _webhook(self, params):
        return self.env['connect.call'].on_call_status(params)

    def test_direct_call_finalizes_when_all_legs_end(self):
        parent_sid = 'CAdirectparent'
        child_sid = 'CAdirectchild'
        base = {
            'Caller': '+13658257665', 'From': '+13658257665',
            'Called': '+19789814066', 'To': '+19789814066',
        }
        client_uri = 'client:%s@%s' % (self.agent.username, self.domain.domain_name)

        # Inbound DID webhook creates the root leg and the call.
        call_id = self._webhook(dict(base, CallSid=parent_sid,
                                     Direction='inbound', CallStatus='ringing',
                                     SequenceNumber='0'))
        call = self.env['connect.call'].browse(call_id)
        self.assertEqual(call.status, 'ringing')

        # Rendering the Dial to the client registers the runtime expectation.
        self.agent._ensure_direct_call_attempt(call, {})
        attempt = call.attempt_ids.filtered(lambda a: a.kind == 'direct_call')
        self.assertEqual(attempt.state, 'pending')

        # The client leg answers, then both legs complete.
        child = dict(base, CallSid=child_sid, ParentCallSid=parent_sid,
                     Called=client_uri, To=client_uri,
                     Direction='outbound-dial')
        self._webhook(dict(child, CallStatus='in-progress', SequenceNumber='1'))
        self._webhook(dict(child, CallStatus='completed', SequenceNumber='2',
                           CallDuration='12'))
        self._webhook(dict(base, CallSid=parent_sid, Direction='inbound',
                           CallStatus='completed', SequenceNumber='1',
                           CallDuration='18'))

        self.assertEqual(attempt.state, 'resolved',
                         'terminal client leg must resolve the expectation')
        self.assertEqual(call.status, 'completed')
        self.assertEqual(call.answered_user, self.agent.user)
        self.assertEqual(call.duration, 30)

    def test_unanswered_leg_still_blocks_until_it_ends(self):
        """The expectation keeps doing its job: a live leg defers finalization."""
        parent_sid = 'CAdirectparent2'
        child_sid = 'CAdirectchild2'
        base = {
            'Caller': '+13658257665', 'From': '+13658257665',
            'Called': '+19789814066', 'To': '+19789814066',
        }
        client_uri = 'client:%s@%s' % (self.agent.username, self.domain.domain_name)

        call_id = self._webhook(dict(base, CallSid=parent_sid,
                                     Direction='inbound', CallStatus='ringing',
                                     SequenceNumber='0'))
        call = self.env['connect.call'].browse(call_id)
        self.agent._ensure_direct_call_attempt(call, {})

        # The client leg is still ringing when the caller hangs up.
        self._webhook(dict(base, CallSid=child_sid, ParentCallSid=parent_sid,
                           Called=client_uri, To=client_uri,
                           Direction='outbound-dial', CallStatus='ringing',
                           SequenceNumber='1'))
        self._webhook(dict(base, CallSid=parent_sid, Direction='inbound',
                           CallStatus='completed', SequenceNumber='1',
                           CallDuration='9'))
        attempt = call.attempt_ids.filtered(lambda a: a.kind == 'direct_call')
        self.assertEqual(attempt.state, 'pending')
        self.assertNotIn(call.status, ('completed', 'no-answer'))

        # The dial leg reports no-answer: now the call can finalize.
        self._webhook(dict(base, CallSid=child_sid, ParentCallSid=parent_sid,
                           Called=client_uri, To=client_uri,
                           Direction='outbound-dial', CallStatus='no-answer',
                           SequenceNumber='2'))
        self._webhook(dict(base, CallSid=parent_sid, Direction='inbound',
                           CallStatus='completed', SequenceNumber='2',
                           CallDuration='9'))
        self.assertEqual(attempt.state, 'resolved')
        self.assertEqual(call.status, 'no-answer')

    def test_short_dialed_ring_group_still_finalizes(self):
        """An expectation Twilio can never satisfy must not deadlock the call.

        A ring group with more than ten routes registers an expected leg
        count above Twilio's parallel-dial limit, so fewer legs than expected
        ever exist. Once the root leg and every created leg have ended, no
        further leg can appear and the call must finalize anyway. Seen live
        with a thirteen-noun ring group that left the call at "ringing".
        """
        parent_sid = 'CAshortparent'
        base = {
            'Caller': '+13658257665', 'From': '+13658257665',
            'Called': '+19789814066', 'To': '+19789814066',
        }
        call_id = self._webhook(dict(base, CallSid=parent_sid,
                                     Direction='inbound', CallStatus='ringing',
                                     SequenceNumber='0'))
        call = self.env['connect.call'].browse(call_id)
        # The callflow registered three expected legs, but Twilio only
        # created two.
        call._set_webhook_expectation('ring_group', {'expected_count': 3})

        for n in (1, 2):
            self._webhook(dict(base, CallSid='CAshortchild%s' % n,
                               ParentCallSid=parent_sid,
                               Called='sip:Agent%s@%s' % (n, self.domain.domain_name),
                               To='sip:Agent%s@%s' % (n, self.domain.domain_name),
                               Direction='outbound-dial',
                               CallStatus='no-answer', SequenceNumber='0'))
        attempt = call.attempt_ids.filtered(lambda a: a.kind == 'ring_group')
        self.assertEqual(attempt.state, 'pending',
                         'parent leg still live: keep waiting')

        self._webhook(dict(base, CallSid=parent_sid, Direction='inbound',
                           CallStatus='completed', SequenceNumber='1',
                           CallDuration='41'))
        self.assertEqual(attempt.state, 'resolved',
                         'no further legs can exist once every leg ended')
        self.assertEqual(call.status, 'no-answer')
