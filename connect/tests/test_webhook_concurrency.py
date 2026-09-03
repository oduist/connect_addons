# -*- coding: utf-8 -*-
from datetime import timedelta
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.connect.models.call import (
    CALL_LOCK_CLASS,
    CALL_SID_LOCK_CLASS,
)


@tagged("post_install", "-at_install")
class TestWebhookConcurrency(TransactionCase):
    """Races between the near-simultaneous Twilio webhooks of one call.

    There is no catching-up cron in the deployments (max_cron_threads = 0):
    a webhook transaction that rolls back is lost forever and the call sticks
    at "ringing". These tests pin the invariants that keep that from
    happening: lock-first ordering, one connect.call per conversation,
    idempotent channel creation, and a transfer dial-action that survives an
    already-existing target channel.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['connect.settings'].set_param('api_url', 'https://pbx.example.com/')
        # The staging template database carries a real OpenAI key; make sure
        # nothing in these tests can reach for it.
        cls.env['connect.settings'].set_param('openai_api_key', False)
        cls.users = cls.env['res.users']
        with patch.object(type(cls.env['connect.settings']), 'get_client',
                          return_value=MagicMock()):
            cls.domain = cls.env['connect.domain'].with_context(
                no_twilio_create=True).create({
                    'subdomain': 'test-races', 'friendly_name': 'Test Races',
                })
            cls.agents = cls.env['connect.user']
            for n in range(2):
                user = cls.env['res.users'].create({
                    'name': 'Race Agent %d' % n,
                    'login': 'race.agent%d@example.com' % n,
                    'email': 'race.agent%d@example.com' % n,
                })
                cls.users |= user
                cls.agents |= cls.env['connect.user'].with_context(
                    no_twilio_create=True).create({
                        'username': 'RaceAgent%d' % n, 'domain': cls.domain.id,
                        'user': user.id,
                        'sip_enabled': True, 'client_enabled': False,
                        'record_calls': False,
                    })
        cls.base = {
            'Caller': '+13658257665', 'From': '+13658257665',
            'Called': '+19789814066', 'To': '+19789814066',
        }

    def _webhook(self, params):
        return self.env['connect.call'].on_call_status(params)

    def _agent_uri(self, n=0):
        return 'sip:%s@%s' % (self.agents[n].username, self.domain.domain_name)

    def _child(self, sid, parent_sid, n=0):
        uri = self._agent_uri(n)
        return dict(self.base, CallSid=sid, ParentCallSid=parent_sid,
                    Called=uri, To=uri, Direction='outbound-dial')

    def test_orphan_children_converge_to_one_call(self):
        """Child legs arriving before their parent share one connect.call,
        and the late parent adopts it instead of creating a second one."""
        parent_sid = 'CAorphanparent'
        self._webhook(dict(self._child('CAorphanchild0', parent_sid, 0),
                           CallStatus='ringing', SequenceNumber='0'))
        self._webhook(dict(self._child('CAorphanchild1', parent_sid, 1),
                           CallStatus='ringing', SequenceNumber='0'))
        channels = self.env['connect.channel'].search(
            [('sid', 'in', ['CAorphanchild0', 'CAorphanchild1'])])
        self.assertEqual(len(channels), 2)
        self.assertEqual(len(channels.mapped('call')), 1,
                         'orphan sibling legs must converge on one call')
        # The parent's first webhook arrives last.
        call_id = self._webhook(dict(
            self.base, CallSid=parent_sid, Direction='inbound',
            CallStatus='ringing', SequenceNumber='0'))
        self.assertEqual(call_id, channels.mapped('call').id,
                         'the late parent must adopt the children\'s call')
        call = self.env['connect.call'].browse(call_id)
        self.assertEqual(call.root_call_sid, parent_sid,
                         'the conversation call must carry its root SID')

    def test_nested_orphan_leg_leaves_no_placeholder_call_behind(self):
        """A grandchild that beats its parent must not litter the call log.

        ParentCallSid is the immediate parent, so a leg of a nested chain
        (root -> mid -> target, as produced by a transfer redirect or the park
        dial-back) that arrives before the mid leg keys a call on the mid SID.
        Once the mid leg shows up the target joins the real conversation, and
        the call it created must go away instead of sitting in the log on a
        live status and holding mid SID against UNIQUE(root_call_sid).
        """
        Call = self.env['connect.call']
        # Two targets dialed from the mid leg arrive first: no parent channel
        # exists yet, so they share a call keyed on the mid SID.
        self._webhook(dict(self._child('CAnested0', 'CAmid', 0),
                           CallStatus='ringing', SequenceNumber='0'))
        self._webhook(dict(self._child('CAnested1', 'CAmid', 1),
                           CallStatus='ringing', SequenceNumber='0'))
        placeholder = Call.search([('root_call_sid', '=', 'CAmid')])
        self.assertEqual(len(placeholder), 1,
                         'the orphan legs must share one placeholder call')
        # The root and then the mid leg arrive; the mid leg joins the root.
        root_call_id = self._webhook(dict(
            self.base, CallSid='CAroot', Direction='inbound',
            CallStatus='ringing', SequenceNumber='0'))
        self._webhook(dict(self._child('CAmid', 'CAroot', 0),
                           CallStatus='ringing', SequenceNumber='0'))
        self.assertEqual(
            self.env['connect.channel'].search(
                [('sid', '=', 'CAmid')]).call.id, root_call_id)
        # The first target's next webhook links its parent and converges. The
        # placeholder still carries its sibling, so it must survive.
        self.assertEqual(
            self._webhook(dict(self._child('CAnested0', 'CAmid', 0),
                               CallStatus='in-progress', SequenceNumber='1')),
            root_call_id)
        self.assertTrue(placeholder.exists(),
                        'a placeholder still holding a leg was deleted')
        # The sibling converges too: nothing is left on the placeholder.
        self.assertEqual(
            self._webhook(dict(self._child('CAnested1', 'CAmid', 1),
                               CallStatus='in-progress', SequenceNumber='1')),
            root_call_id)
        self.assertFalse(placeholder.exists(),
                         'the emptied placeholder call was not dropped')
        self.assertFalse(Call.search([('root_call_sid', '=', 'CAmid')]),
                         'the mid SID still blocks UNIQUE(root_call_sid)')
        self.assertEqual(
            len(self.env['connect.channel'].search(
                [('sid', 'in', ['CAnested0', 'CAnested1'])])), 2,
            'dropping the placeholder cascaded onto its former legs')

    def test_placeholder_with_a_recording_is_kept(self):
        """Only an empty placeholder may be dropped."""
        self._webhook(dict(self._child('CArecnested', 'CArecmid', 0),
                           CallStatus='ringing', SequenceNumber='0'))
        placeholder = self.env['connect.call'].search(
            [('root_call_sid', '=', 'CArecmid')])
        self.env['connect.recording'].create({
            'call': placeholder.id, 'sid': 'REtest', 'call_sid': 'CArecnested',
        })
        root_call_id = self._webhook(dict(
            self.base, CallSid='CArecroot', Direction='inbound',
            CallStatus='ringing', SequenceNumber='0'))
        self._webhook(dict(self._child('CArecmid', 'CArecroot', 0),
                           CallStatus='ringing', SequenceNumber='0'))
        self._webhook(dict(self._child('CArecnested', 'CArecmid', 0),
                           CallStatus='in-progress', SequenceNumber='1'))
        self.assertTrue(placeholder.exists(),
                        'a call carrying a recording was deleted')
        self.assertEqual(root_call_id, self.env['connect.channel'].search(
            [('sid', '=', 'CArecnested')]).call.id)

    def test_duplicate_root_sid_is_refused_by_the_database(self):
        """UNIQUE(root_call_sid) is the backstop for call-creation races the
        snapshot cannot see."""
        self._webhook(dict(self.base, CallSid='CAuroot', Direction='inbound',
                           CallStatus='ringing', SequenceNumber='0'))
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self.env['connect.call'].create({
                    'caller': '+15550001111', 'called': '+15550002222',
                    'direction': 'incoming', 'status': 'ringing',
                    'root_call_sid': 'CAuroot',
                })

    def test_duplicate_sid_create_race_recovers(self):
        """A lost duplicate-SID race converges on the winner row instead of
        rolling back the webhook transaction."""
        params = dict(self.base, CallSid='CAracesid', Direction='inbound',
                      CallStatus='ringing', SequenceNumber='0')
        first_call_id = self._webhook(params)
        Channel = type(self.env['connect.channel'])
        orig_search = Channel.search
        state = {'skipped': False}

        def racing_search(model, domain, *args, **kwargs):
            # Simulate the race window: the first SID lookup misses the row a
            # concurrent transaction has just committed.
            if (not state['skipped'] and domain
                    and list(domain[0]) == ['sid', '=', 'CAracesid']):
                state['skipped'] = True
                return model.browse()
            return orig_search(model, domain, *args, **kwargs)

        with patch.object(Channel, 'search', racing_search):
            call_id = self._webhook(dict(params, CallStatus='in-progress',
                                         SequenceNumber='1'))
        self.assertTrue(state['skipped'], 'the race window must have opened')
        self.assertEqual(call_id, first_call_id)
        channels = self.env['connect.channel'].search(
            [('sid', '=', 'CAracesid')])
        self.assertEqual(len(channels), 1, 'no duplicate channel row')
        self.assertEqual(channels.status, 'in-progress',
                         'the retried webhook must apply as an update')
        # The transaction survived the confined IntegrityError.
        self.env.cr.execute('SELECT 1')
        self.assertEqual(self.env.cr.fetchone()[0], 1)

    def test_advisory_locks_taken_in_order(self):
        """The root-SID lock exists from the very first webhook (when no call
        row exists yet), and the per-call lock joins it afterwards."""
        parent_sid = 'CAlockorder'
        call_id = self._webhook(dict(
            self.base, CallSid=parent_sid, Direction='inbound',
            CallStatus='ringing', SequenceNumber='0'))
        self.env.cr.execute("SELECT hashtext(%s)", (parent_sid,))
        sid_key = self.env.cr.fetchone()[0]
        self.env.cr.execute(
            """
            SELECT classid::bigint, objid::bigint
              FROM pg_locks
             WHERE locktype = 'advisory' AND pid = pg_backend_pid()
            """)
        held = {tuple(row) for row in self.env.cr.fetchall()}
        # objid is unsigned in pg_locks; normalize both sides to unsigned.
        self.assertIn((CALL_SID_LOCK_CLASS, sid_key & 0xFFFFFFFF),
                      {(c & 0xFFFFFFFF, o & 0xFFFFFFFF) for c, o in held},
                      'root-SID advisory lock must be held')
        self.assertIn((CALL_LOCK_CLASS & 0xFFFFFFFF, call_id & 0xFFFFFFFF),
                      {(c & 0xFFFFFFFF, o & 0xFFFFFFFF) for c, o in held},
                      'per-call advisory lock must be held')

    def test_transfer_dial_action_with_existing_target_channel(self):
        """The Dial action webhook must not poison the transaction when the
        transfer target's channel already exists (its own status webhooks
        arrived first)."""
        parent_sid, child_sid, target_sid = 'CAtfparent', 'CAtfchild', 'CAtftarget'
        call_id = self._webhook(dict(
            self.base, CallSid=parent_sid, Direction='inbound',
            CallStatus='ringing', SequenceNumber='0'))
        call = self.env['connect.call'].browse(call_id)
        self.agents[0]._ensure_direct_call_attempt(call, {})
        child = self._child(child_sid, parent_sid, 0)
        self._webhook(dict(child, CallStatus='in-progress', SequenceNumber='1'))
        call.add_transferred_user(self.users[1])
        call.store_transfer_context(target_sid, self.users[1])
        target = self._child(target_sid, child_sid, 1)
        self._webhook(dict(target, CallStatus='in-progress', SequenceNumber='1'))
        self._webhook(dict(child, CallStatus='completed', SequenceNumber='2',
                           CallDuration='20'))
        # Target channel exists; before the fix this INSERTed a duplicate SID
        # and aborted the transaction for good.
        response = self.env['connect.call'].on_call_action({
            'CallSid': child_sid, 'DialCallSid': target_sid,
            'DialCallStatus': 'completed', 'DialCallDuration': '15',
        })
        self.assertIn('Hangup', response)
        self.env.cr.execute('SELECT 1')  # transaction is still alive
        target_channel = self.env['connect.channel'].search(
            [('sid', '=', target_sid)])
        self.assertEqual(len(target_channel), 1)
        self.assertEqual(target_channel.status, 'completed')
        self._webhook(dict(target, CallStatus='completed', SequenceNumber='2',
                           CallDuration='15'))
        self._webhook(dict(self.base, CallSid=parent_sid, Direction='inbound',
                           CallStatus='completed', SequenceNumber='1',
                           CallDuration='40'))
        self.assertEqual(call.status, 'completed')

    def test_out_of_order_parent_completion_still_finalizes(self):
        """Twilio does not order webhooks across legs: when the parent's
        completed webhook lands before the last child's terminal webhook,
        the closing child webhook must finalize the call — otherwise it is
        stuck on a live status forever (no cron exists to repair it)."""
        parent_sid, child_sid = 'CAoooparent', 'CAooochild'
        call_id = self._webhook(dict(
            self.base, CallSid=parent_sid, Direction='inbound',
            CallStatus='ringing', SequenceNumber='0'))
        call = self.env['connect.call'].browse(call_id)
        self.agents[0]._ensure_direct_call_attempt(call, {})
        child = self._child(child_sid, parent_sid, 0)
        self._webhook(dict(child, CallStatus='in-progress', SequenceNumber='1'))
        # The parent's completed webhook is processed FIRST.
        self._webhook(dict(self.base, CallSid=parent_sid, Direction='inbound',
                           CallStatus='completed', SequenceNumber='1',
                           CallDuration='18'))
        self.assertNotEqual(call.status, 'completed',
                            'child leg still active, no finalization yet')
        # The child's terminal webhook closes the conversation.
        self._webhook(dict(child, CallStatus='completed', SequenceNumber='2',
                           CallDuration='12'))
        self.assertEqual(call.status, 'completed')
        self.assertEqual(call.answered_user, self.users[0])

    def test_park_retrieval_claim_is_atomic(self):
        """Only one retrieval claims a parked call; a failed Twilio redirect
        compensates by restoring the slot."""
        call = self.env['connect.call'].create({
            'caller': '+12898283865', 'called': '+13658257665',
            'direction': 'incoming', 'status': 'in-progress',
        })
        self.env['connect.channel'].create({
            'sid': 'CAparked', 'call': call.id, 'caller': '+12898283865',
            'called': '+13658257665', 'status': 'in-progress',
            'technical_direction': 'inbound',
        })
        call.write({
            'park_slot': '702', 'park_call_sid': 'CAparked',
            'parked_at': fields.Datetime.now(),
        })
        request = {'Caller': self._agent_uri(0)}
        client = MagicMock()
        with patch.object(type(self.env['connect.settings']), 'get_client',
                          return_value=client):
            Call = self.env['connect.call']
            self.assertTrue(Call._dial_back_parked_call(
                call, self.agents[0], '702', request))
            self.assertFalse(call.park_slot, 'slot must be claimed')
            self.assertEqual(call.park_call_sid, 'CAparked',
                             'park_call_sid is kept for the re-park action')
            # Second retrieval of the same slot loses the claim.
            self.assertFalse(Call._dial_back_parked_call(
                call, self.agents[0], '702', request))
            # Failed redirect: claim is compensated, the slot stays registered.
            call.write({'park_slot': '702'})
            client.calls.side_effect = Exception('twilio down')
            self.assertFalse(Call._dial_back_parked_call(
                call, self.agents[0], '702', request))
            self.assertEqual(call.park_slot, '702',
                             'failed redirect must restore the slot')

    def test_has_pending_webhooks_is_pure(self):
        """The predicate ignores overdue attempts without mutating them —
        expiring is _refresh_runtime_attempts()'s job."""
        call_id = self._webhook(dict(
            self.base, CallSid='CApurepred', Direction='inbound',
            CallStatus='ringing', SequenceNumber='0'))
        call = self.env['connect.call'].browse(call_id)
        attempt = call._set_webhook_expectation('direct_call', {
            'expected_count': 1, 'target_user_id': self.users[0].id,
        })
        self.assertTrue(call._has_pending_webhooks())
        attempt.write({
            'expires_at': fields.Datetime.now() - timedelta(minutes=1)})
        self.assertFalse(call._has_pending_webhooks())
        self.assertEqual(attempt.state, 'pending',
                         'the predicate must not write')
        call._refresh_runtime_attempts()
        self.assertEqual(attempt.state, 'expired')
