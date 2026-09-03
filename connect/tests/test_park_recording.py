# -*- coding: utf-8 -*-
from unittest.mock import MagicMock, patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestParkRecording(TransactionCase):
    """Both halves of a parked conversation are recorded, and both are shown.

    Parking ends the first <Dial>, so a retrieved call produces one recording
    per segment. Every segment is stored on the call whose <Dial> ran, i.e. the
    original inbound one; the retrieval leg owns none.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['connect.settings'].set_param('api_url', 'https://pbx.example.com/')
        with patch.object(type(cls.env['connect.settings']), 'get_client',
                          return_value=MagicMock()):
            cls.domain = cls.env['connect.domain'].with_context(
                no_twilio_create=True).create({
                    'subdomain': 'test-park-rec', 'friendly_name': 'Test Park Rec',
                })
            # Answered the call originally, records everything.
            cls.answerer = cls.env['connect.user'].with_context(
                no_twilio_create=True).create({
                    'username': 'RecAnswerer', 'domain': cls.domain.id,
                    'sip_enabled': True, 'client_enabled': False,
                    'record_calls': True,
                })
            # Picks the call up from the slot, records nothing.
            cls.retriever = cls.env['connect.user'].with_context(
                no_twilio_create=True).create({
                    'username': 'RecRetriever', 'domain': cls.domain.id,
                    'sip_enabled': True, 'client_enabled': False,
                    'record_calls': False,
                })
        cls.retriever_uri = 'sip:RecRetriever@%s' % cls.domain.domain_name

    def _make_call(self, sid, caller, called, direction, **vals):
        call = self.env['connect.call'].create(dict({
            'caller': caller, 'called': called, 'direction': direction,
            'status': 'in-progress',
        }, **vals))
        self.env['connect.channel'].create({
            'sid': sid, 'call': call.id, 'caller': caller, 'called': called,
            'status': 'in-progress', 'technical_direction': 'inbound',
        })
        return call

    def _parked_call(self, **vals):
        return self._make_call('CAcustomer', '+12898283865', '+13658257665',
                               'incoming', **vals)

    def _add_recording(self, call, sid, duration):
        # skip_transcription also skips the commit connect.recording.create()
        # does to survive transcription errors, which a test cursor forbids.
        return self.env['connect.recording'].with_context(
            skip_transcription=True).create({
                'call': call.id, 'sid': sid, 'call_sid': 'CAcustomer',
                'duration': duration, 'status': 'completed',
            })

    # ------------------------------------------------------------------
    # The retrieval leg is recorded per the call's policy, not the agent's
    # ------------------------------------------------------------------

    def test_retrieval_is_recorded_when_the_retriever_does_not_record(self):
        """The half after the pickup must not vanish because the agent who
        happened to take the call has recording switched off."""
        parked = self._parked_call(answered_pbx_user=self.answerer.id)
        twiml = self.env['connect.call']._build_park_retrieval_twiml(
            parked, self.retriever, '702')
        self.assertIn('record="record-from-answer-dual"', str(twiml))
        self.assertIn('recordingStatusCallback', str(twiml))

    def test_retrieval_is_not_recorded_when_the_answerer_does_not_record(self):
        """A conversation nobody recorded stays unrecorded after retrieval."""
        self.answerer.record_calls = False
        self.retriever.record_calls = True
        parked = self._parked_call(answered_pbx_user=self.answerer.id)
        twiml = self.env['connect.call']._build_park_retrieval_twiml(
            parked, self.retriever, '702')
        self.assertNotIn('record="record-from-answer-dual"', str(twiml))

    def test_retrieval_respects_the_call_recording_opt_out(self):
        parked = self._parked_call(answered_pbx_user=self.answerer.id,
                                   disable_recording=True)
        twiml = self.env['connect.call']._build_park_retrieval_twiml(
            parked, self.retriever, '702')
        self.assertNotIn('record="record-from-answer-dual"', str(twiml))

    def test_retrieval_falls_back_to_the_retriever_when_nobody_is_known(self):
        """Calls parked before the answering user was tracked keep the old
        behaviour rather than silently losing their recording."""
        self.retriever.record_calls = True
        parked = self._parked_call()
        self.assertFalse(parked.answered_pbx_user)
        twiml = self.env['connect.call']._build_park_retrieval_twiml(
            parked, self.retriever, '702')
        self.assertIn('record="record-from-answer-dual"', str(twiml))

    # ------------------------------------------------------------------
    # Every segment is visible
    # ------------------------------------------------------------------

    def test_call_lists_every_recorded_segment(self):
        """A parked and retrieved call has more than one recording; the form
        used to show only the newest."""
        parked = self._parked_call(answered_pbx_user=self.answerer.id)
        before = self._add_recording(parked, 'REbefore', 53)
        after = self._add_recording(parked, 'REafter', 21)
        self.assertEqual(parked.recording_ids, before | after)
        self.assertEqual(parked.recording, after,
                         'The player should still open the latest segment.')

    def test_retrieval_leg_shows_the_recordings_of_the_call_it_retrieved(self):
        """The "agent -> slot" leg owns no recording, so without this it opens
        an empty Recording tab."""
        parked = self._parked_call(answered_pbx_user=self.answerer.id)
        recording = self._add_recording(parked, 'REbefore', 53)
        retrieval = self._make_call('CAretrieval', '206', '702', 'outgoing',
                                    parent_call=parked.id)
        self.assertFalse(
            self.env['connect.recording'].search([('call', '=', retrieval.id)]))
        self.assertEqual(retrieval.recording_ids, recording)
        self.assertEqual(retrieval.recording, recording)
        self.assertTrue(retrieval.recording_icon)

    def test_a_call_without_recordings_stays_empty(self):
        call = self._parked_call()
        self.assertFalse(call.recording_ids)
        self.assertFalse(call.recording)
        self.assertFalse(call.recording_icon)
