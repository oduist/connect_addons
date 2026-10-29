# -*- coding: utf-8 -*-
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.connect.models.recording import twilio_mp3_url

TWILIO_RECORDING = ('https://api.twilio.com/2010-04-01/Accounts/AC0000/'
                    'Recordings/RE0123456789abcdef0123456789abcdef')
WHISPER_URL = 'http://whisper.test:9000/v1'
TWILIO_AUTH = ('AC0000', 'twilio-token')


def fake_transcription():
    return SimpleNamespace(segments=[
        SimpleNamespace(start=0.0, text=' Hello'),
        SimpleNamespace(start=65.2, text=' Bye'),
    ])


def fake_download(url, **kwargs):
    response = MagicMock()
    response.iter_content.return_value = [b'audio-bytes']
    response.content = b'audio-bytes'
    response.headers = {'Content-Type': 'audio/ogg'}
    return response


@tagged('post_install', '-at_install')
class TestWhisperTranscription(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.settings = cls.env['connect.settings'].sudo()
        for param, value in [
            ('openai_api_key', 'sk-test'),
            ('transcript_provider', 'whisper'),
            ('whisper_api_url', WHISPER_URL),
            ('whisper_api_key', 'whisper-key'),
            ('whisper_model', 'large-v3-turbo'),
            ('whisper_language', False),
            ('account_sid', TWILIO_AUTH[0]),
            ('auth_token', TWILIO_AUTH[1]),
            ('region_auth_token', False),
        ]:
            cls.settings.set_param(param, value)

    def _patch_clients(self):
        """Patch openai.OpenAI; return {'whisper'|'openai': [(kwargs, client)]}."""
        clients = {}

        def make_client(**kwargs):
            client = MagicMock()
            client.audio.transcriptions.create.return_value = fake_transcription()
            client.chat.completions.create.return_value = SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='Call summary'))],
                usage=None)
            kind = 'whisper' if 'base_url' in kwargs else 'openai'
            clients.setdefault(kind, []).append((kwargs, client))
            return client

        patcher = patch('odoo.addons.connect.models.settings.openai.OpenAI',
                        side_effect=make_client)
        patcher.start()
        self.addCleanup(patcher.stop)
        return clients

    @staticmethod
    def _calls(clients, kind, method):
        """Calls of `method` ('transcribe' or 'summarise') across all clients of a kind."""
        calls = []
        for kwargs, client in clients.get(kind, []):
            mock = (client.audio.transcriptions.create if method == 'transcribe'
                    else client.chat.completions.create)
            calls += mock.call_args_list
        return calls

    def _recording(self):
        return self.env['connect.recording'].with_context(skip_transcription=True).create({
            'sid': 'RE0123456789abcdef0123456789abcdef', 'call_sid': 'CAwhisper',
            'media_url': TWILIO_RECORDING,
        })

    def test_twilio_mp3_url(self):
        self.assertEqual(twilio_mp3_url(TWILIO_RECORDING), TWILIO_RECORDING + '.mp3')
        regional = TWILIO_RECORDING.replace('api.twilio.com', 'api.dublin.ie1.twilio.com')
        self.assertEqual(twilio_mp3_url(regional), regional + '.mp3')
        for url in (TWILIO_RECORDING + '.mp3',
                    'https://oduist-connect-x.s3.eu-central-1.amazonaws.com/recordings/RE1.wav',
                    'https://api.twilio.com/2010-04-01/Accounts/AC0000/Messages/MM1/Media/ME1',
                    False):
            self.assertEqual(twilio_mp3_url(url), url)

    def test_twilio_media_auth(self):
        auth = self.settings.get_twilio_media_auth
        self.assertEqual(auth(TWILIO_RECORDING), TWILIO_AUTH)
        message_media = 'https://api.twilio.com/2010-04-01/Accounts/AC0000/Messages/MM1/Media/ME1'
        self.assertEqual(auth(message_media), TWILIO_AUTH)
        regional = TWILIO_RECORDING.replace('api.twilio.com', 'api.dublin.ie1.twilio.com')
        self.assertEqual(auth(regional), TWILIO_AUTH)
        self.settings.set_param('region_auth_token', 'region-token')
        self.assertEqual(auth(regional), (TWILIO_AUTH[0], 'region-token'))
        self.assertEqual(auth(TWILIO_RECORDING), TWILIO_AUTH)
        # Credentials never leave Twilio's own API hosts.
        for url in ('https://oduist-connect-x.s3.eu-central-1.amazonaws.com/recordings/RE1.wav',
                    'http://api.twilio.com/2010-04-01/Accounts/AC0000/Recordings/RE1',
                    'https://api.twilio.com.evil.example/Recordings/RE1',
                    'https://api.x.twilio.com@evil.example/Recordings/RE1',
                    'https://media.example.com/voice.ogg',
                    False):
            self.assertIsNone(auth(url), url)
        self.settings.set_param('auth_token', False)
        self.settings.set_param('region_auth_token', False)
        self.assertIsNone(auth(TWILIO_RECORDING))

    def test_recording_transcribed_by_whisper_summarised_by_openai(self):
        clients = self._patch_clients()
        recording = self._recording()
        with patch('odoo.addons.connect.models.recording.requests.get',
                   side_effect=fake_download) as download:
            recording.get_transcript()
        self.assertEqual(download.call_args.args[0], TWILIO_RECORDING + '.mp3')
        self.assertEqual(download.call_args.kwargs['auth'], TWILIO_AUTH)
        whisper_kwargs = clients['whisper'][0][0]
        self.assertEqual(whisper_kwargs['base_url'], WHISPER_URL)
        self.assertEqual(whisper_kwargs['api_key'], 'whisper-key')
        self.assertEqual(whisper_kwargs['max_retries'], 0)
        [transcribe] = self._calls(clients, 'whisper', 'transcribe')
        self.assertEqual(transcribe.kwargs['model'], 'large-v3-turbo')
        self.assertEqual(transcribe.kwargs['response_format'], 'verbose_json')
        self.assertNotIn('language', transcribe.kwargs)
        self.assertFalse(self._calls(clients, 'whisper', 'summarise'))
        self.assertEqual(clients['openai'][0][0]['api_key'], 'sk-test')
        self.assertFalse(self._calls(clients, 'openai', 'transcribe'))
        self.assertEqual(len(self._calls(clients, 'openai', 'summarise')), 1)
        self.assertEqual(recording.transcript, '00:00:00  Hello\n00:01:05  Bye\n')
        self.assertIn('Call summary', recording.summary)
        self.assertFalse(recording.transcription_error)

    def test_whisper_language_is_sent_when_set(self):
        self.settings.set_param('whisper_language', ' fr ')
        clients = self._patch_clients()
        with patch('odoo.addons.connect.models.recording.requests.get',
                   side_effect=fake_download):
            self._recording().get_transcript()
        [transcribe] = self._calls(clients, 'whisper', 'transcribe')
        self.assertEqual(transcribe.kwargs['language'], 'fr')

    def test_openai_provider_unchanged(self):
        self.settings.set_param('transcript_provider', 'openai')
        clients = self._patch_clients()
        recording = self._recording()
        with patch('odoo.addons.connect.models.recording.requests.get',
                   side_effect=fake_download):
            recording.get_transcript()
        self.assertNotIn('whisper', clients)
        [transcribe] = self._calls(clients, 'openai', 'transcribe')
        self.assertEqual(transcribe.kwargs['model'], 'whisper-1')
        self.assertNotIn('language', transcribe.kwargs)
        self.assertEqual(len(self._calls(clients, 'openai', 'summarise')), 1)
        self.assertEqual(recording.transcript, '00:00:00  Hello\n00:01:05  Bye\n')

    def test_missing_configuration(self):
        self.settings.set_param('whisper_api_url', False)
        self.assertEqual(self.settings.get_stt_error(), 'Whisper API URL is not set!')
        with self.assertRaisesRegex(ValidationError, 'Whisper API URL is not set'):
            self._recording().get_transcript()
        # Whisper does not need an OpenAI key; the OpenAI provider does.
        self.settings.set_param('whisper_api_url', WHISPER_URL)
        self.settings.set_param('openai_api_key', False)
        self.assertFalse(self.settings.get_stt_error())
        self.settings.set_param('transcript_provider', 'openai')
        self.assertEqual(self.settings.get_stt_error(), 'OpenAI key is not set!')

    def test_voicemail_uses_whisper_without_openai_key(self):
        self.settings.set_param('openai_api_key', False)
        clients = self._patch_clients()
        with patch('odoo.addons.connect.models.voicemail.requests.get',
                   side_effect=fake_download) as download:
            voicemail = self.env['connect.voicemail'].sudo().create({
                'media_url': TWILIO_RECORDING, 'duration': 24,
            })
        self.assertEqual(download.call_args.args[0], TWILIO_RECORDING + '.mp3')
        self.assertEqual(download.call_args.kwargs['auth'], TWILIO_AUTH)
        self.assertNotIn('openai', clients)
        self.assertEqual(voicemail.transcript, 'Hello\n Bye')
        self.assertFalse(voicemail.transcription_error)

    def test_voice_message_sent_in_its_own_format(self):
        clients = self._patch_clients()
        media_url = 'https://api.twilio.com/2010-04-01/Accounts/AC0000/Messages/MM1/Media/ME1'
        with patch('odoo.addons.connect.models.message.requests.get',
                   side_effect=fake_download) as download:
            result = self.env['connect.message'].transcribe_voice_message(
                media_url, 'audio/ogg')
        self.assertEqual(download.call_args.args[0], media_url)
        self.assertEqual(download.call_args.kwargs['auth'], TWILIO_AUTH)
        [transcribe] = self._calls(clients, 'whisper', 'transcribe')
        self.assertEqual(transcribe.kwargs['file'], ('voice.ogg', b'audio-bytes', 'audio/ogg'))
        self.assertEqual(result, {'body': 'Hello\n Bye'})

    def test_voice_file_name(self):
        message = self.env['connect.message']
        self.assertEqual(message._voice_file_name('audio/ogg; codecs=opus'), 'voice.ogg')
        self.assertEqual(message._voice_file_name('audio/mpeg'), 'voice.mp3')
        self.assertEqual(message._voice_file_name('audio/amr'), 'voice.amr')
        self.assertEqual(message._voice_file_name(None), 'voice.mp3')

    def test_whisper_key_is_masked(self):
        record = self.settings.browse(self.settings._settings_record_id())
        record.write({'display_whisper_api_key': 'new-secret'})
        self.assertEqual(record.whisper_api_key, 'new-secret')
        self.assertEqual(record.display_whisper_api_key, '*' * len('new-secret'))

    def test_action_test_whisper(self):
        record = self.settings.browse(self.settings._settings_record_id())
        client = MagicMock()
        models = client.with_options.return_value.models
        models.list.return_value = [SimpleNamespace(id='whisper-1')]
        with patch('odoo.addons.connect.models.settings.openai.OpenAI', return_value=client):
            self.assertTrue(record.action_test_whisper())
            client.with_options.assert_called_once_with(timeout=15)
            models.list.side_effect = Exception('connection refused')
            with self.assertRaisesRegex(ValidationError, 'connection refused'):
                record.action_test_whisper()
