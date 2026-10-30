# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

QUEUE_LOGGER = 'odoo.addons.connect.models.transcription_queue'
RECORDING_URL = ('https://api.twilio.com/2010-04-01/Accounts/AC0000/'
                 'Recordings/RE0123456789abcdef0123456789abcdef')


@tagged('post_install', '-at_install')
class TestTranscriptionQueue(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.settings = cls.env['connect.settings'].sudo()
        for param, value in [
            ('openai_api_key', 'sk-test'),
            ('transcript_provider', 'openai'),
            ('transcript_calls', True),
        ]:
            cls.settings.set_param(param, value)
        cls.env['connect.transcription_rule'].search([]).unlink()
        cls.rule = cls.env['connect.transcription_rule'].create({
            'calling_number': '.*', 'called_number': '.*'})
        cls.cron = cls.env.ref('connect.transcribe_queue')
        cls.call = cls.env['connect.call'].sudo().create({
            'caller': '+15551230000', 'called': '+15550000000',
            'direction': 'incoming', 'status': 'completed',
        })

    def setUp(self):
        super().setUp()
        # Outside a cron run _commit_progress commits, which a test cursor forbids.
        self.time_left = 1
        self.patch(self.registry['ir.cron'], '_commit_progress',
                   lambda cron_model, processed=0, remaining=None, **kwargs: self.time_left)
        self.transcribed = []
        self.notifications = []

        def fake_recording(rec, openai_api_key, summary_prompt):
            self.transcribed.append(rec)
            if rec.sid == 'REfails':
                raise RuntimeError('STT server down')
            rec.write({'transcript': 'Hello', 'transcription_error': False})

        def fake_voicemail(rec):
            self.transcribed.append(rec)
            rec.write({'transcript': 'Call me back', 'transcription_error': False})

        def fake_notify(settings, message, title='Connect', notify_uid=None, sticky=False, warning=False):
            self.notifications.append((notify_uid, title, message, warning))
            return True

        self.patch(self.registry['connect.recording'], 'transcribe_recording', fake_recording)
        self.patch(self.registry['connect.voicemail'], 'transcribe_voicemail', fake_voicemail)
        self.patch(self.registry['connect.settings'], 'connect_notify', fake_notify)

    def _triggers(self):
        return self.env['ir.cron.trigger'].sudo().search_count([('cron_id', '=', self.cron.id)])

    def _recording(self, sid='RE0123456789abcdef0123456789abcdef', **vals):
        return self.env['connect.recording'].create(dict({
            'sid': sid, 'call_sid': 'CAqueue', 'media_url': RECORDING_URL, 'call': self.call.id,
        }, **vals))

    def test_new_recording_is_queued_not_transcribed(self):
        triggers = self._triggers()
        with patch('odoo.addons.connect.models.recording.requests.get') as download:
            recording = self._recording()
        download.assert_not_called()
        self.assertFalse(self.transcribed)
        self.assertTrue(recording.transcription_pending)
        self.assertFalse(recording.transcription_requested_by)
        self.assertEqual(self._triggers(), triggers + 1)

    def test_recording_not_queued(self):
        # No matching rule, transcription off, or the skip context.
        self.rule.unlink()
        self.assertFalse(self._recording().transcription_pending)
        self.env['connect.transcription_rule'].create({'calling_number': '.*', 'called_number': '.*'})
        self.assertFalse(self.env['connect.recording'].with_context(skip_transcription=True).create({
            'sid': 'REskip', 'call_sid': 'CAqueue', 'media_url': RECORDING_URL,
        }).transcription_pending)
        self.assertFalse(self._recording(sid='REnomedia', media_url=False).transcription_pending)
        self.settings.set_param('openai_api_key', False)
        self.assertFalse(self._recording(sid='REnokey').transcription_pending)
        self.settings.set_param('openai_api_key', 'sk-test')
        self.settings.set_param('transcript_calls', False)
        self.assertFalse(self._recording(sid='REoff').transcription_pending)

    def test_cron_transcribes_queue(self):
        recording = self._recording()
        self.settings._cron_transcribe_queue()
        self.assertEqual(self.transcribed, [recording])
        self.assertEqual(recording.transcript, 'Hello')
        self.assertFalse(recording.transcription_pending)
        # Queued automatically: nobody to notify.
        self.assertFalse(self.notifications)

    def test_transcribe_button_queues_and_notifies(self):
        recording = self.env['connect.recording'].with_context(skip_transcription=True).create({
            'sid': 'REbutton', 'call_sid': 'CAqueue', 'media_url': RECORDING_URL,
        })
        action = recording.get_transcript()
        self.assertEqual(action['tag'], 'display_notification')
        self.assertFalse(self.transcribed)
        self.assertTrue(recording.transcription_pending)
        self.assertEqual(recording.transcription_requested_by, self.env.user)
        self.settings._cron_transcribe_queue()
        self.assertEqual(recording.transcript, 'Hello')
        self.assertFalse(recording.transcription_requested_by)
        [(uid, title, message, warning)] = self.notifications
        self.assertEqual(uid, self.env.uid)
        self.assertEqual(title, 'Transcription')
        self.assertIn('Recording %s' % recording.id, message)
        self.assertFalse(warning)

    def test_button_raises_on_bad_settings(self):
        recording = self._recording()
        self.settings.set_param('openai_api_key', False)
        with self.assertRaisesRegex(ValidationError, 'OpenAI key is not set'):
            recording.get_transcript()

    @mute_logger(QUEUE_LOGGER)
    def test_error_is_recorded_and_queue_goes_on(self):
        failing = self._recording(sid='REfails')
        failing.get_transcript()
        ok = self._recording(sid='REworks')
        self.settings._cron_transcribe_queue()
        self.assertEqual(self.transcribed, [failing, ok])
        self.assertEqual(failing.transcription_error, 'STT server down')
        self.assertFalse(failing.transcription_pending)
        self.assertEqual(ok.transcript, 'Hello')
        [(uid, title, message, warning)] = self.notifications
        self.assertEqual(title, 'Transcription failed')
        self.assertIn('STT server down', message)
        self.assertTrue(warning)

    @mute_logger(QUEUE_LOGGER)
    def test_settings_checked_again_when_transcribing(self):
        recording = self._recording()
        self.settings.set_param('openai_api_key', False)
        self.settings._cron_transcribe_queue()
        self.assertFalse(self.transcribed)
        self.assertEqual(recording.transcription_error, 'OpenAI key is not set!')
        self.assertFalse(recording.transcription_pending)

    def test_voicemails_first_then_recordings(self):
        recording = self._recording()
        with patch('odoo.addons.connect.models.voicemail.requests.get') as download:
            voicemail = self.env['connect.voicemail'].sudo().create({
                'media_url': RECORDING_URL, 'duration': 24})
        download.assert_not_called()
        self.assertTrue(voicemail.transcription_pending)
        self.settings._cron_transcribe_queue()
        self.assertEqual(self.transcribed, [voicemail, recording])
        self.assertEqual(voicemail.transcript, 'Call me back')
        self.assertFalse(voicemail.transcription_pending)

    def test_voicemail_button(self):
        voicemail = self.env['connect.voicemail'].with_context(skip_transcription=True).sudo().create({
            'media_url': RECORDING_URL, 'duration': 24})
        self.assertFalse(voicemail.transcription_pending)
        self.assertEqual(voicemail.get_transcript()['tag'], 'display_notification')
        self.assertEqual(voicemail.transcription_requested_by, self.env.user)
        voicemail.media_url = False
        with self.assertRaisesRegex(ValidationError, 'not available yet'):
            voicemail.get_transcript()

    def test_cron_stops_when_out_of_time(self):
        first = self._recording(sid='REfirst')
        second = self._recording(sid='REsecond')
        self.time_left = 0
        self.settings._cron_transcribe_queue()
        self.assertEqual(self.transcribed, [first])
        self.assertTrue(second.transcription_pending)
