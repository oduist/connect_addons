# -*- coding: utf-8 -*-
import io
import logging

import requests

from odoo import api, fields, models, release

logger = logging.getLogger(__name__)


class Recording(models.Model):
    _inherit = 'connect.recording'

    elevenlabs_transcript = fields.Text(readonly=True)
    elevenlabs_summary = fields.Text(readonly=True)
    elevenlabs_media_file = fields.Binary()
    list_summary = fields.Html(compute='_compute_list_summary', string='List Summary')
    if release.version_info[0] >= 17.0:
        elevenlabs_recording_widget = fields.Html(compute='_elevenlabs_recording_widget',
                                                  sanitize=False)
    else:
        elevenlabs_recording_widget = fields.Char(compute='_elevenlabs_recording_widget')

    def _elevenlabs_recording_widget(self):
        for rec in self:
            rec.elevenlabs_recording_widget = '<audio id="sound_file" preload="auto" ' \
                'controls="controls"> ' \
                '<source src="/web/content?model=connect.recording&' \
                'id={recording_id}&filename={filename}&field={source}&' \
                'filename_field=recording_filename&download=True" />' \
                '</audio>'.format(
                    recording_id=rec.id,
                    filename='elevenlabs_recording.mp3',
                    source='elevenlabs_media_file')

    @api.depends('summary', 'elevenlabs_summary')
    def _compute_list_summary(self):
        """Compute list_summary by prioritizing elevenlabs_summary over summary"""
        for rec in self:
            if rec.elevenlabs_summary:
                rec.list_summary = rec.elevenlabs_summary
            else:
                rec.list_summary = rec.summary or ''

    def _get_list_view_summary(self):
        for rec in self:
            if rec.elevenlabs_summary:
                rec.list_view_summary = rec.elevenlabs_summary
            else:
                rec.list_view_summary = rec.summary

    def transcribe_recording(self, openai_api_key, summary_prompt):
        if not self.env['connect.license'].check_license('connect_elevenlabs', silent=True):
            return super().transcribe_recording(openai_api_key, summary_prompt)
        transcript_provider = self.env['connect.settings'].sudo().get_param('transcript_provider')
        if transcript_provider == 'elevenlabs':
            client = self.env['connect.settings'].get_elevenlabs_client()

            response = requests.get(self.media_url)
            response.raise_for_status()
            audio_file = io.BytesIO(response.content)

            logger.info('Transcribe with Elevenlabs provider!')
            result = {'transcription_error': False}
            try:
                response = client.speech_to_text.convert(
                    file=audio_file,
                    model_id="scribe_v1",  # Model to use, for now only "scribe_v1" is supported
                    diarize=True,  # Whether to annotate who is speaking
                    tag_audio_events=False,  # Tag audio events like laughter, applause, etc.
                )
                logger.info(f'Transcript: {response.text}')
                print(response)
                result['transcript'] = response.text if response.text else ""
                # Make a summary
                openai_client = self.env['connect.settings'].get_openai_client()
                result.update(self.make_summary(openai_client, summary_prompt, result['transcript']))
            except Exception as e:
                logger.exception(f"Transcribe error: {e}")
                result['transcription_error'] = str(e)
            finally:
                self.write(result)
        else:
            return super().transcribe_recording(openai_api_key, summary_prompt)
