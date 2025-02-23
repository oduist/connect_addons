# -*- coding: utf-8 -*-

import json
import logging
import os
import re
import requests
from tempfile import NamedTemporaryFile
from urllib.parse import urljoin
import uuid
from odoo import fields, models, api, release, SUPERUSER_ID
from odoo.exceptions import ValidationError
import httpx
import openai
from .settings import format_connect_response, debug

logger = logging.getLogger(__name__)


class TranscriptionRules(models.Model):
    _name = 'connect.transcription_rule'
    _description = 'Transcription rule'
    _order = 'id'

    settings = fields.Many2one('connect.settings', required=True, default=1)
    calling_number = fields.Char(required=True)
    called_number = fields.Char(required=True)

    @api.model
    def check_rules(self, calling_number, called_number):
        for rec in self.search([]):
            try:
                if calling_number and not re.search(rec.calling_number, calling_number):
                    debug(self, 'Transcription rule {} calling number pattern does not match'.format(rec.id))
                    continue
                if called_number and not re.search(rec.called_number, called_number):
                    debug(self, 'Transcription rule {} called number pattern does not match'.format(rec.id))
                    continue
                debug(self, 'Transcription rule {} matched!'.format(rec.id))
                return True
            except Exception as e:
                logger.error('Error checking transcription rule %s: %s', rec.id, e)


class Recording(models.Model):
    _name = 'connect.recording'
    _description = 'Recording'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'id'
    _order = 'id desc'

    call = fields.Many2one('connect.call', ondelete='set null')
    channel = fields.Many2one('connect.channel', ondelete='set null')
    partner = fields.Many2one('res.partner', ondelete='set null')
    sid = fields.Char('SID', readonly=True, required=True)
    # It's a channel sid actually.
    call_sid = fields.Char(required=True, string='Channel SID', readonly=True)
    caller_user = fields.Many2one('res.users', ondelete='set null')
    called_user = fields.Many2one('res.users', ondelete='set null')
    caller_number = fields.Char()
    called_number = fields.Char()
    media_url = fields.Char()
    price = fields.Char()
    price_unit = fields.Char()
    source = fields.Char()
    duration = fields.Integer()
    duration_human = fields.Char(compute='_get_duration_human')
    start_time = fields.Datetime()
    status = fields.Char()
    if release.version_info[0] >= 17.0:
        recording_widget = fields.Html(compute='_get_recording_widget', string='Recording', sanitize=False)
    else:
        recording_widget = fields.Char(compute='_get_recording_widget', string='Recording')
    ############## TRANSCRIPTION FIELDS ######################################
    transcript = fields.Text()
    transcription_token = fields.Char()
    transcription_error = fields.Char()
    transcription_price = fields.Char()
    summary = fields.Html()

    ############## TRANSCRIPTION METHODS #####################################

    def transcribe_recording(self, openai_api_key, summary_prompt):
        result = {}
        try:
            if os.environ.get('OPENAI_PROXY'):
                client = openai.OpenAI(
                    api_key=openai_api_key, http_client=httpx.Client(proxy=os.environ.get('HTTPS_PROXY')))
            else:
                client = openai.OpenAI(api_key=openai_api_key)
            response = requests.get(self.media_url, stream=True)
            response.raise_for_status()
            with NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
                # Write the content from the URL to the temporary file
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        temp_file.write(chunk)
                temp_file_path = temp_file.name
            with open(temp_file_path, 'rb') as audio_file:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1", file=audio_file,
                    response_format='verbose_json', timestamp_granularities=["segment"])
                # result['minutes'] = round(transcript.duration / 60.0, 2)
            # Create segments
            segments = ''
            for s in transcript.segments:
                seconds = int(s.start)
                ts = f"{int(seconds // 3600):02d}:{int((seconds % 3600) // 60):02d}:{int(seconds % 60):02d}"
                segments += '{} {}\n'.format(ts, s.text)
            result['transcript'] = segments
            # Make a summary
            response = client.chat.completions.create(
                model=os.environ.get('OPENAI_COMPLETION_MODEL', 'gpt-4o'),
                messages=[
                    {
                        'role': 'user',
                        'content': summary_prompt
                    },
                    {
                        'role': 'user',
                        'content': segments,
                    },
                ],
                temperature=float(os.environ.get('OPENAI_COMPLETION_TEMPERATURE', 0.5)),
                max_tokens=int(os.environ.get('OPENAI_COMPLETION_MAX_TOKENS', 4096)),
                top_p=float(os.environ.get('OPENAI_COMPLETION_TOP_P', 1.0)),
                frequency_penalty=float(os.environ.get('OPENAI_COMPLETION_FREQUENCY_PENALTY', 0.0)),
                presence_penalty=float(os.environ.get('OPENAI_COMPLETION_PRESENSE_PENALTY', 0.0)),
            )
            logger.info('%s', response.usage)
            #result['finish_reason'] = response.choices[0].finish_reason
            #result['completion_tokens'] = response.usage.completion_tokens
            #result['prompt_tokens'] = response.usage.prompt_tokens
            result['summary'] = response.choices[0].message.content.strip('\n\n')
            #result['completion_model'] = completion_model
            #result['prompt'] = summary_prompt
            result['transcription_error'] = False
        except Exception as e:
            logger.exception('Transcribe error:')
            result['transcription_error'] = str(e)
        finally:
            self.write(result)


    def get_transcript(self, fail_silently=False):
        self.ensure_one()
        openai_key = self.env['connect.settings'].sudo().get_param('openai_api_key')
        if not openai_key:
            if fail_silently:
                logger.warning('OpenAI key is not set! Transcription will not be available.')
                return False
            else:
                raise ValidationError('OpenAI key is not set!')
        summary_prompt = self.env['connect.settings'].get_param('summary_prompt')
        # First check if the call matches the transcription rules.
        if fail_silently and not self.env['connect.transcription_rule'].sudo().check_rules(
                self.call.caller, self.call.called):
            debug(self, 'No transcription rules matched.')
            return False
        if not self.media_url:
            raise ValidationError('Recording is not available yet!')
        self.transcribe_recording(openai_key, summary_prompt)

    def update_transcript(self, data):
        # Update transcription and also erase access token.
        self.ensure_one()
        transcription_price = data.get('transcription_price')
        if transcription_price:
            # Round
            transcription_price = round(transcription_price, 2)
        vals = {
            'transcript': data.get('transcript'),
            'transcription_price': str(transcription_price),
            'summary': data.get('summary'),
            # Reset the token
            'transcription_token': False,
            'transcription_error': data.get('transcription_error')
        }
        self.with_context(tracking_disable=True).write(vals)
        # Update call summary.
        if self.call:
            self.call.summary = data.get('summary')
        # Reload views when transcription has come.
        self.env['connect.settings'].pbx_reload_view('connect.recording')
        # Notify user
        if data.get('notify_uid'):
            self.env['connect.settings'].connect_notify(
                'Transcription updated', notify_uid=data['notify_uid'])

##########  END OF TRANSCRIPTION METHODS #########################################################

    def _get_recording_widget(self):
        proxy_recordings = self.env['connect.settings'].sudo().get_param('proxy_recordings')
        for rec in self:
            if proxy_recordings:
                media_url = '/connect/recording/{}'.format(rec.id)
            else:
                media_url = rec.media_url
            rec.recording_widget = '<audio id="sound_file" preload="auto" ' \
                'controls="controls"> ' \
                '<source src="{}"/>' \
                '</audio>'.format(media_url)

    @api.model
    def prepare_data(self, rec):
        data = {}
        for field in ['sid', 'call_sid', 'media_url', 'price', 'price_unit',
                      'duration', 'source', 'start_time','status']:
            data[field] = getattr(rec, field)
            if field in ['start_time', 'date_created', 'date_updated']:
                # Parse 2024-05-29 21:44:48+00:00
                data[field] = data[field].utcnow()
        channel = self.env['connect.channel'].search([('sid', '=', rec.call_sid)])
        data['call'] = channel.call.id
        data['channel'] = channel.id
        return data

    def sync(self):
        client = self.env['connect.settings'].get_client()
        for rec in self:
            recording = client.recordings(rec.sid).fetch()
            data = self.prepare_data(recording)
            rec.write(data)

    @api.model_create_multi
    def create(self, vals_list):
        transcript_calls = self.env['connect.settings'].sudo().get_param('transcript_calls')
        recs = super(Recording, self.with_context(
            mail_create_nosubscribe=True, mail_create_nolog=True)).create(vals_list)
        # Commit to the database so that transcription error will not break the recording.
        self.env.cr.commit()
        if transcript_calls:
            for rec in recs:
                try:
                    rec.get_transcript(fail_silently=True)
                except Exception as e:
                    logger.exception('Transcript error:')
        return recs

    @api.model
    def on_recording_status(self, params):
        self = self.sudo()
        debug(self, 'On recording status: %s' % json.dumps(params, indent=2))
        # Todo: RecordingChannels
        data = {
            'sid': params['RecordingSid'],
            'call_sid': params['CallSid'],
            'duration': params['RecordingDuration'],
            'status': params['RecordingStatus']
        }
        channel = self.env['connect.channel'].search([('sid', '=', params['CallSid'])])
        if channel:
            call = channel.call
            data['channel'] = channel.id
            data['call'] = call.id
            data['partner'] = call.partner.id
            data['caller_user'] = channel.caller_user.id
            data['called_user'] = channel.called_user.id
            data['caller_number'] = call.caller
            data['called_number'] = call.called
        # Fetch recording
        client = self.env['connect.settings'].get_client()
        try:
            recording = client.recordings(data['sid']).fetch()
            data.update(self.prepare_data(recording))
        except Exception as e:
            logger.error(format_connect_response(e))
        self.create(data)
        return True

    @api.depends('duration')
    def _get_duration_human(self):
        for record in self:
            if record.duration is not None:
                # Compute minutes and seconds
                minutes = record.duration // 60
                seconds = record.duration % 60
                # Format human-readable time as MM:SS
                record.duration_human = '{:02}:{:02}'.format(minutes, seconds)
            else:
                record.duration_human = "00:00"

    @api.constrains('summary')
    def _sync_summary(self):
        # When recording transcription summary is set we update related object summary.
        if self.call:
            self.with_user(SUPERUSER_ID).call.summary = self.summary
