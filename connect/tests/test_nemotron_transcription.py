# -*- coding: utf-8 -*-
import base64
import io
import wave
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import openai

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

from odoo.addons.connect.models import stt_utils

TWILIO_RECORDING = ('https://api.twilio.com/2010-04-01/Accounts/AC0000/'
                    'Recordings/RE0123456789abcdef0123456789abcdef')
NEMOTRON_URL = 'http://nemotron.test:9001/v1'
SETTINGS = 'odoo.addons.connect.models.settings'
# MPEG-2 Layer III, 64 kbps, 22.05 kHz, joint stereo -- Twilio's MP3 rendition:
# 208-byte frames of 576 samples.
MP3_FRAME = bytes([0xFF, 0xF3, 0x80, 0x64]) + b'\0' * 204
MP3_FRAME_SECONDS = 576 / 22050


def mp3(seconds, id3=True):
    frames = MP3_FRAME * (int(seconds / MP3_FRAME_SECONDS) + 1)
    tag = b'ID3\x03\x00\x00\x00\x00\x00\x0a' + b'x' * 10 if id3 else b''
    return tag + frames + b'TAG' + b'\0' * 125


def wav(seconds, rate=8000, channels=2):
    out = io.BytesIO()
    with wave.open(out, 'wb') as target:
        target.setnchannels(channels)
        target.setsampwidth(2)
        target.setframerate(rate)
        target.writeframes(b'\1\0' * channels * int(rate * seconds))
    return out.getvalue()


def completion(text, finish_reason='stop'):
    return SimpleNamespace(choices=[SimpleNamespace(
        finish_reason=finish_reason, message=SimpleNamespace(content=text))], usage=None)


@tagged('post_install', '-at_install')
class TestSttUtils(TransactionCase):
    def test_sniff_audio_mime(self):
        self.assertEqual(stt_utils.sniff_audio_mime(mp3(1)), 'audio/mpeg')
        self.assertEqual(stt_utils.sniff_audio_mime(mp3(1, id3=False)), 'audio/mpeg')
        self.assertEqual(stt_utils.sniff_audio_mime(wav(1)), 'audio/wav')
        self.assertEqual(stt_utils.sniff_audio_mime(b'OggS\0\2' + b'\0' * 20), 'audio/ogg')
        self.assertEqual(stt_utils.sniff_audio_mime(b'#!AMR\n' + b'\0' * 20), 'audio/amr')
        self.assertEqual(stt_utils.sniff_audio_mime(b'\0\0\0\x20ftypM4A '), 'audio/mp4')
        self.assertEqual(stt_utils.sniff_audio_mime(b'garbage', 'audio/x-unknown'), 'audio/x-unknown')

    def test_split_mp3_on_frames_with_overlap(self):
        data = mp3(25)
        self.assertEqual(len(stt_utils.mp3_frames(data)), int(25 / MP3_FRAME_SECONDS) + 1)
        chunks = stt_utils.split_mp3(data, 10, 1)
        self.assertEqual([(start, round(end, 1)) for start, end, _blob in chunks],
                         [(0.0, 11.0), (10.0, 21.0), (20.0, 25.0)])
        for start, end, blob in chunks:
            self.assertEqual(blob[:4], MP3_FRAME[:4])
            self.assertEqual(len(blob) % len(MP3_FRAME), 0)
            self.assertAlmostEqual(len(blob) // len(MP3_FRAME) * MP3_FRAME_SECONDS, end - start, delta=0.05)
        self.assertIsNone(stt_utils.split_mp3(b'no frames here', 10, 1))

    def test_short_tail_joins_previous_chunk(self):
        chunks = stt_utils.split_mp3(mp3(21.5), 10, 1)
        self.assertEqual([start for start, _end, _blob in chunks], [0.0, 10.0])
        self.assertEqual(len(stt_utils.split_mp3(mp3(8), 10, 1)), 1)

    def test_split_wav(self):
        chunks = stt_utils.split_audio(wav(25), 'audio/wav', 10, 1)
        self.assertEqual([(start, end) for start, end, _blob in chunks],
                         [(0.0, 11.0), (10.0, 21.0), (20.0, 25.0)])
        for start, end, blob in chunks:
            with wave.open(io.BytesIO(blob)) as part:
                self.assertEqual(part.getnchannels(), 2)
                self.assertEqual(part.getframerate(), 8000)
                self.assertEqual(part.getnframes(), int((end - start) * 8000))
        self.assertIsNone(stt_utils.split_audio(b'RIFF\0\0\0\0WAVEbroken', 'audio/wav', 10, 1))
        self.assertIsNone(stt_utils.split_audio(b'OggS', 'audio/ogg', 10, 1))

    def test_stitch(self):
        self.assertEqual(stt_utils.stitch([
            'Hello there, how are you today?',
            'How are you today? I am fine, thanks.',
            'I am fine, thanks. Bye.',
        ]), ['Hello there,', 'How are you today?', 'I am fine, thanks. Bye.'])
        # Fewer than three words in common: no seam, nothing dropped.
        self.assertEqual(stt_utils.stitch(['one two', 'two three']), ['one two', 'two three'])
        self.assertEqual(stt_utils.stitch(['', 'alone']), ['', 'alone'])


@tagged('post_install', '-at_install')
class TestNemotronTranscription(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.settings = cls.env['connect.settings'].sudo()
        for param, value in [
            ('openai_api_key', 'sk-test'),
            ('transcript_provider', 'nemotron'),
            ('nemotron_api_url', NEMOTRON_URL),
            ('nemotron_api_key', 'nemotron-key'),
            ('nemotron_model', 'nemotron-3.5-transcribe'),
            ('nemotron_prompt', 'Transcribe this call to Mirage Pools.'),
            ('account_sid', 'AC0000'),
            ('auth_token', 'twilio-token'),
        ]:
            cls.settings.set_param(param, value)

    def setUp(self):
        super().setUp()
        self.patch(self.registry['ir.cron'], '_commit_progress',
                   lambda cron_model, processed=0, remaining=None, **kwargs: 1)
        self.startPatcher(patch(SETTINGS + '.NEMOTRON_CHUNK_SECONDS', 10))
        self.startPatcher(patch(SETTINGS + '.NEMOTRON_OVERLAP_SECONDS', 1))
        self.replies = []
        self.clients = {}

        def make_client(**kwargs):
            client = MagicMock()
            if kwargs.get('base_url') == NEMOTRON_URL:
                client.chat.completions.create.side_effect = self.replies
                self.clients['nemotron'] = (kwargs, client)
            else:
                client.chat.completions.create.return_value = completion('Call summary')
                self.clients['openai'] = (kwargs, client)
            return client

        self.startPatcher(patch(SETTINGS + '.openai.OpenAI', side_effect=make_client))

    def _requests(self):
        return self.clients['nemotron'][1].chat.completions.create.call_args_list

    def _audio(self, request):
        """(mime, bytes) of the audio a request sent."""
        url = request.kwargs['messages'][0]['content'][1]['audio_url']['url']
        header, payload = url.split(',', 1)
        return header[len('data:'):-len(';base64')], base64.b64decode(payload)

    def _download(self, data):
        def fake_get(url, **kwargs):
            response = MagicMock()
            response.iter_content.return_value = [data]
            response.content = data
            return response
        return patch('odoo.addons.connect.models.recording.requests.get', side_effect=fake_get)

    def _recording(self):
        return self.env['connect.recording'].with_context(skip_transcription=True).create({
            'sid': 'RE0123456789abcdef0123456789abcdef', 'call_sid': 'CAnemotron',
            'media_url': TWILIO_RECORDING,
        })

    def _transcribe(self, recording):
        recording.get_transcript()
        self.settings._cron_transcribe_queue()

    def test_recording_in_chunks(self):
        self.replies[:] = [
            completion('Hello there, how are you today?'),
            completion('How are you today? I am fine, thanks.'),
            completion('I am fine, thanks. Bye.'),
        ]
        recording = self._recording()
        with self._download(mp3(25)):
            self._transcribe(recording)
        self.assertFalse(recording.transcription_error)
        self.assertEqual(recording.transcript,
                         '00:00:00  Hello there,\n00:00:10  How are you today?\n'
                         '00:00:20  I am fine, thanks. Bye.\n')
        self.assertIn('Call summary', recording.summary)
        kwargs = self.clients['nemotron'][0]
        self.assertEqual((kwargs['base_url'], kwargs['api_key'], kwargs['max_retries']),
                         (NEMOTRON_URL, 'nemotron-key', 0))
        requests = self._requests()
        self.assertEqual(len(requests), 3)
        for request in requests:
            self.assertEqual(request.kwargs['model'], 'nemotron-3.5-transcribe')
            self.assertEqual(request.kwargs['temperature'], 0)
            self.assertEqual(request.kwargs['max_tokens'], 2048)
            self.assertEqual(request.kwargs['extra_body'],
                             {'chat_template_kwargs': {'enable_thinking': False}})
            prompt = request.kwargs['messages'][0]['content'][0]
            self.assertEqual(prompt, {'type': 'text', 'text': 'Transcribe this call to Mirage Pools.'})
            mime, audio = self._audio(request)
            self.assertEqual(mime, 'audio/mpeg')
            self.assertEqual(audio[:4], MP3_FRAME[:4])
        # The summary still comes from OpenAI.
        self.assertEqual(self.clients['openai'][1].chat.completions.create.call_count, 1)

    def test_size_limit_does_not_apply(self):
        self.replies[:] = [completion('Short call.')]
        recording = self._recording()
        with self._download(mp3(5)), \
                patch('odoo.addons.connect.models.recording.os.path.getsize', return_value=26214401):
            self._transcribe(recording)
        self.assertFalse(recording.transcription_error)
        self.assertEqual(recording.transcript, '00:00:00  Short call.\n')

    @mute_logger('odoo.addons.connect.models.recording')
    def test_truncated_transcript_is_an_error(self):
        self.replies[:] = [completion('Hello', finish_reason='length')]
        recording = self._recording()
        with self._download(mp3(5)):
            self._transcribe(recording)
        self.assertIn('cut the transcript short', recording.transcription_error)
        self.assertFalse(recording.transcript)

    def test_wav_is_split(self):
        # The middle chunk only repeats its neighbours: no segment for it.
        self.replies[:] = [completion('one two three four five'), completion('three four five'),
                           completion('three four five six')]
        result = self.settings.transcribe_audio(io.BytesIO(wav(25)))
        self.assertEqual([self._audio(r)[0] for r in self._requests()], ['audio/wav'] * 3)
        self.assertEqual([(s.start, s.text) for s in result.segments],
                         [(0.0, ' one two'), (20.0, ' three four five six')])
        self.assertEqual(result.text, 'one two three four five six')

    def test_voice_message_sent_whole(self):
        self.replies[:] = [completion('Please call me back.')]
        media_url = 'https://api.twilio.com/2010-04-01/Accounts/AC0000/Messages/MM1/Media/ME1'
        ogg = b'OggS\0\2' + b'\0' * 100
        response = MagicMock(content=ogg, headers={'Content-Type': 'audio/ogg'})
        with patch('odoo.addons.connect.models.message.requests.get', return_value=response):
            result = self.env['connect.message'].transcribe_voice_message(media_url, 'audio/ogg; codecs=opus')
        self.assertEqual(result, {'body': 'Please call me back.'})
        [request] = self._requests()
        self.assertEqual(self._audio(request), ('audio/ogg', ogg))

    def test_audio_too_long_for_one_request(self):
        error = openai.BadRequestError.__new__(openai.BadRequestError)
        Exception.__init__(error, 'Error code: 400 - The decoder prompt contains a(n) audio item with '
                                  '6281 embedding tokens, which exceeds the pre-allocated encoder cache size 4096.')
        self.replies[:] = [error]
        with self.assertRaisesRegex(ValidationError, 'only MP3 and PCM WAV audio can be split'):
            self.settings.transcribe_audio(('voice.ogg', b'OggS' + b'\0' * 100, 'audio/ogg'))

    def test_missing_configuration(self):
        self.settings.set_param('nemotron_api_url', False)
        self.assertEqual(self.settings.get_stt_error(), 'Nemotron API URL is not set!')
        with self.assertRaisesRegex(ValidationError, 'Nemotron API URL is not set'):
            self._recording().get_transcript()
        # Nemotron needs no OpenAI key to transcribe; the recording summary does.
        self.settings.set_param('nemotron_api_url', NEMOTRON_URL)
        self.settings.set_param('openai_api_key', False)
        self.assertFalse(self.settings.get_stt_error())

    def test_nemotron_key_is_masked(self):
        record = self.settings.browse(self.settings._settings_record_id())
        record.write({'display_nemotron_api_key': 'new-secret'})
        self.assertEqual(record.nemotron_api_key, 'new-secret')
        self.assertEqual(record.display_nemotron_api_key, '*' * len('new-secret'))

    def test_action_test_nemotron(self):
        record = self.settings.browse(self.settings._settings_record_id())
        client = MagicMock()
        client.with_options.return_value.models.list.return_value = [
            SimpleNamespace(id='nemotron-3.5-transcribe')]
        notifications = []
        self.patch(self.registry['connect.settings'], 'connect_notify',
                   lambda settings, message, **kwargs: notifications.append((message, kwargs['title'])))
        with patch(SETTINGS + '.openai.OpenAI', return_value=client):
            self.assertTrue(record.action_test_nemotron())
        self.assertEqual(notifications, [
            ('Nemotron server is reachable. Models: nemotron-3.5-transcribe', 'Nemotron')])
        self.settings.set_param('nemotron_api_url', False)
        with self.assertRaisesRegex(ValidationError, 'Nemotron API URL is not set'):
            record.action_test_nemotron()
